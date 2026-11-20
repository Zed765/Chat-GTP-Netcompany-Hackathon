"""Activity-log ingestion: inspect prompts that were sent without the gateway in the path.

Nothing is forwarded and nothing is put in the vault. Each prompt becomes one event that
says what was in it and what the active policy would have done. The event never claims the
gateway saw the prompt on its way out.
"""

from collections import Counter

from gateway.app.core.interfaces import Detector, Inventory, PolicyService
from gateway.app.core.types import (
    Action,
    Channel,
    ContextualDetection,
    Finding,
    LocalDetection,
    PolicyContext,
)
from gateway.app.events.writer import ORIGIN_IMPORT, ORIGIN_LOG, EventRecord, EventWriter
from gateway.app.privacy.directory import Directory
from gateway.app.proxy.inspection import SNIPPET_CHARS, summarise
from gateway.app.proxy.schemas import IngestResult, PromptRecord


def mask_by_type(text: str, findings: tuple[Finding, ...]) -> str:
    """Replace each maskable finding with its type, for example `<AFM>`."""
    masked = text
    for finding in reversed(findings):
        if finding.maskable:
            masked = f"{masked[: finding.start]}<{finding.data_type}>{masked[finding.end :]}"
    return masked


async def _event(
    record: PromptRecord,
    local: LocalDetection,
    masked: str,
    contextual: ContextualDetection,
    policy: PolicyService,
    inventory: Inventory,
    directory: Directory,
) -> EventRecord:
    tool = await inventory.resolve(record.tool)
    team = directory.team_of(user_id=record.user_id)
    found, counts = summarise(local.findings, contextual.categories)
    context = PolicyContext(
        channel=Channel.PROMPT,
        data_types=frozenset(counts),
        tool=tool.slug,
        tool_status=tool.status,
        team=team,
        detector_error=contextual.error is not None,
    )
    decision = await policy.decide(context, found)
    stopped = record.enforced and decision.action in (Action.BLOCK, Action.WARN)
    return EventRecord(
        ts=record.ts,
        user_id=record.user_id,
        team=team,
        channel=Channel.PROMPT,
        action=decision.action,
        rule=decision.rule,
        policy_version=decision.policy_version,
        tool=tool.slug,
        tool_status=tool.status,
        data_counts=counts,
        timings_ms={**local.timings_ms, **contextual.timings_ms},
        usage=contextual.usage,
        masked_snippet=masked[:SNIPPET_CHARS] if local.findings else None,
        origin=ORIGIN_IMPORT if record.enforced else ORIGIN_LOG,
        forwarded=not stopped,
        policy_context=context,
        error=contextual.error,
    )


async def ingest_prompts(
    records: list[PromptRecord],
    *,
    detector: Detector,
    policy: PolicyService,
    inventory: Inventory,
    directory: Directory,
    events: EventWriter,
) -> IngestResult:
    locals_ = [await detector.detect_local(record.text) for record in records]
    masked = [
        mask_by_type(record.text, local.findings)
        for record, local in zip(records, locals_, strict=True)
    ]
    # One embedding request for the batch, and never one model call per logged prompt.
    contextual = await detector.detect_contextual_many(masked, use_model=False)
    inspected = [
        await _event(*row, policy, inventory, directory)
        for row in zip(records, locals_, masked, contextual, strict=True)
    ]
    await events.write_many(inspected)
    actions = Counter(event.action for event in inspected)
    return IngestResult(ingested=len(inspected), actions=dict(actions))
