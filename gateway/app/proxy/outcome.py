"""What happens after inspection: build the caller's trace, refuse, or prepare to forward."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from gateway.app.core.interfaces import Rehydrator
from gateway.app.core.types import Action, Principal, RehydrationReport, ToolRef, ToolStatus
from gateway.app.events.writer import EventRecord
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.inspection import Inspection
from gateway.app.proxy.payload import Reading, UninspectedError
from gateway.app.proxy.schemas import (
    PolicyError,
    PolicyErrorResponse,
    SpanView,
    Trace,
    TraceSummary,
    UpstreamMessage,
)

TRACE_ID_HEADER = "X-Aspida-Trace-Id"
ACTION_HEADER = "X-Aspida-Action"
RULE_HEADER = "X-Aspida-Rule"


async def inspect_request(
    ctx: ProxyContext,
    principal: Principal,
    tool: ToolRef,
    read: Callable[..., Reading],
    payload: dict[str, Any],
    *,
    conversation: str | None,
) -> tuple[Reading, Inspection]:
    """Read the request, inspect it and write the masked texts into `payload`. A field the
    gateway will not forward is answered with a 400 that names it. A tool the company
    approved may receive parts the gateway cannot read, such as images."""
    conversation_id, vault_id = ctx.conversation(principal, conversation)
    try:
        reading = read(payload, opaque_allowed=tool.status is ToolStatus.APPROVED)
        inspection = await ctx.inspector.inspect(
            principal=principal,
            tool=tool,
            conversation_id=conversation_id,
            vault_id=vault_id,
            reading=reading,
        )
    except UninspectedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    for slot, masked in zip(reading.texts, inspection.masked, strict=True):
        slot.write(masked.text)
    return reading, inspection


def build_trace(
    inspection: Inspection,
    *,
    upstream_messages: list[UpstreamMessage],
    spans: list[SpanView],
    forwarded: bool,
    needs_acknowledgement: bool = False,
) -> Trace:
    decision = inspection.decision
    return Trace(
        trace_id=inspection.trace_id,
        conversation_id=inspection.conversation_id,
        tool=inspection.tool,
        action=decision.action,
        rule=decision.rule,
        policy_version=decision.policy_version,
        explanation=decision.explanation,
        forwarded=forwarded,
        needs_acknowledgement=needs_acknowledgement,
        upstream_messages=upstream_messages,
        spans=spans,
        tiers_run=list(inspection.tiers_run),
        timings_ms={tier.value: round(ms, 2) for tier, ms in inspection.timings_ms.items()},
    )


def decision_headers(inspection: Inspection) -> dict[str, str]:
    return {
        TRACE_ID_HEADER: inspection.trace_id,
        ACTION_HEADER: inspection.decision.action.value,
        RULE_HEADER: inspection.decision.rule,
    }


@dataclass(frozen=True)
class Verdict:
    """Either a refusal to send back as it is, or permission to forward."""

    refusal: JSONResponse | None
    masked: bool
    recorded: bool = False


async def settle(
    ctx: ProxyContext,
    principal: Principal,
    inspection: Inspection,
    trace: Trace,
    *,
    acknowledged: str | None,
) -> Verdict:
    """Apply the decision. A block or a warning is recorded and refused here until the user
    confirms it; a confirmed one is recorded as forwarded and goes on with the masked text."""
    action = inspection.decision.action
    if action is Action.ALLOW:
        return Verdict(refusal=None, masked=False)
    if action is Action.REDACT:
        return Verdict(refusal=None, masked=True)
    if action in (Action.WARN, Action.BLOCK) and acknowledged:
        if not await ctx.events.mark_forwarded(acknowledged, principal.user_id):
            await ctx.events.write(inspection.event(principal, forwarded=True))
        return Verdict(refusal=None, masked=True, recorded=True)

    await ctx.events.write(inspection.event(principal, forwarded=False))
    blocked = action is Action.BLOCK
    body = PolicyErrorResponse(
        error=PolicyError(
            message=inspection.decision.explanation.summary,
            type="aspida_policy_block" if blocked else "aspida_policy_warning",
            code=inspection.decision.rule,
        ),
        aspida=trace.model_copy(update={"needs_acknowledgement": not blocked}),
    )
    return Verdict(
        refusal=JSONResponse(
            body.model_dump(mode="json"),
            status_code=403 if blocked else 409,
            headers=decision_headers(inspection),
        ),
        masked=True,
        recorded=True,
    )


_pending_writes: set[asyncio.Task[int]] = set()


def record_after_stream(ctx: ProxyContext, record: EventRecord) -> None:
    """Write the event of a streamed answer without waiting for it. A caller who hangs up
    cancels the stream, and the event must be recorded all the same."""
    task = asyncio.create_task(ctx.events.write(record))
    _pending_writes.add(task)
    task.add_done_callback(_pending_writes.discard)


class Restorer:
    """Restores placeholders across however many text streams one response has, and adds up
    what came back."""

    def __init__(self, ctx: ProxyContext, inspection: Inspection, *, active: bool) -> None:
        self._vault = ctx.vault
        self._inspection = inspection
        self._active = active
        self._streams: dict[str, Rehydrator] = {}
        self._returned = 0
        self._unresolved: list[str] = []

    async def feed(self, stream: str, chunk: str) -> str:
        if not self._active:
            return chunk
        if stream not in self._streams:
            self._streams[stream] = await self._vault.rehydrator(
                self._inspection.vault_id, self._inspection.placeholders
            )
        return self._streams[stream].feed(chunk)

    def flush(self, stream: str) -> str:
        rehydrator = self._streams.pop(stream, None)
        if rehydrator is None:
            return ""
        tail = rehydrator.flush()
        self._count(rehydrator.report())
        return tail

    async def whole(self, text: str, *, counted: bool = True) -> str:
        """Restore a complete text. Pass `counted=False` for text already seen as a stream."""
        if not self._active:
            return text
        restored, report = await self._vault.resolve(self._inspection.vault_id, text)
        if counted:
            self._count(report)
        return restored

    def _count(self, report: RehydrationReport) -> None:
        self._returned += report.returned
        self._unresolved.extend(report.unresolved)

    def report(self) -> RehydrationReport:
        sent = len(self._inspection.placeholders) if self._active else 0
        return RehydrationReport(
            sent=sent,
            returned=min(self._returned, sent),
            unresolved=tuple(dict.fromkeys(self._unresolved)),
        )

    def summary(self) -> TraceSummary:
        return TraceSummary(
            trace_id=self._inspection.trace_id,
            rehydration=self.report(),
            usage=self._inspection.usage,
            latency_ms=round(self._inspection.elapsed_ms(), 2),
        )
