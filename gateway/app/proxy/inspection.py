"""The inspection half of the prompt path: detect locally, mask, look at the masked text,
decide by policy. Forwarding and restoring live in `chat.py` and `responses.py`."""

import re
import time
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate
from uuid import uuid4

from gateway.app.core.interfaces import Detector, PolicyService, Vault
from gateway.app.core.types import (
    Action,
    CategoryFinding,
    Channel,
    Finding,
    FoundItem,
    LocalDetection,
    MaskedSpan,
    MaskResult,
    PolicyContext,
    PolicyDecision,
    Principal,
    Tier,
    ToolRef,
    Usage,
)
from gateway.app.events.writer import EventRecord
from gateway.app.mcp_proxy.sessions import CANARY_PREFIX
from gateway.app.proxy.payload import Name, Reading, UninspectedError
from gateway.app.proxy.schemas import SpanView

SNIPPET_CHARS = 200
# Names are detected as one text, a paragraph apart so that none continues another.
_NAME_BREAK = "\n\n"
# The gateway's own tripwire in an agent's instructions. It must reach the model as written.
_CANARY = re.compile(re.escape(CANARY_PREFIX) + r"[0-9a-f]{16}")


@dataclass(frozen=True)
class Inspection:
    """Everything known about a request before anything is forwarded."""

    trace_id: str
    conversation_id: str
    vault_id: str
    tool: ToolRef
    context: PolicyContext
    decision: PolicyDecision
    masked: tuple[MaskResult, ...]
    timings_ms: dict[Tier, float]
    tiers_run: tuple[Tier, ...]
    data_counts: dict[str, int]
    usage: Usage
    error: str | None
    started: float

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(span.placeholder for result in self.masked for span in result.spans)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    def span_views(self, index: int) -> list[SpanView]:
        """Every finding in one text, masked or only flagged, in order of appearance."""
        result = self.masked[index]
        views = [
            _span_view(span.start, span.end, span.placeholder, span) for span in result.spans
        ] + [_span_view(found.start, found.end, None, found) for found in result.unmasked]
        return sorted(views, key=lambda view: view.start)

    def snippet(self) -> str | None:
        """The start of the newest text, kept only if something in it was masked."""
        newest = self.masked[-1] if self.masked else None
        if newest is None or not newest.spans:
            return None
        return newest.text[:SNIPPET_CHARS]

    def event(
        self,
        principal: Principal,
        *,
        action: Action | None = None,
        forwarded: bool,
        usage: Usage | None = None,
    ) -> EventRecord:
        return EventRecord(
            user_id=principal.user_id,
            team=principal.team,
            channel=self.context.channel,
            action=action or self.decision.action,
            rule=self.decision.rule,
            policy_version=self.decision.policy_version,
            tool=self.tool.slug,
            tool_status=self.tool.status,
            data_counts=self.data_counts,
            timings_ms=self.timings_ms,
            latency_ms=self.elapsed_ms(),
            usage=self.usage + (usage or Usage()),
            masked_snippet=self.snippet(),
            conversation_id=self.conversation_id,
            trace_id=self.trace_id,
            forwarded=forwarded,
            policy_context=self.context,
            error=self.error,
        )


def _span_view(
    start: int, end: int, placeholder: str | None, found: MaskedSpan | Finding
) -> SpanView:
    match = found.match
    return SpanView(
        start=start,
        end=end,
        placeholder=placeholder,
        data_type=found.data_type,
        tier=found.tier,
        recogniser=found.recogniser,
        encoded=found.encoded,
        store=match.store if match else None,
        source=match.source if match else None,
        match_label=match.label if match else None,
    )


def summarise(
    findings: Sequence[Finding], categories: Sequence[CategoryFinding]
) -> tuple[list[FoundItem], dict[str, int]]:
    """Findings grouped for the explanation, and the per-type counts an event stores."""
    counts: Counter[str] = Counter()
    first: dict[str, Finding] = {}
    for finding in findings:
        counts[finding.data_type] += 1
        first.setdefault(finding.data_type, finding)
    items = [
        FoundItem(
            data_type=data_type,
            count=count,
            tier=first[data_type].tier,
            encoded=any(f.encoded for f in findings if f.data_type == data_type),
            match_label=match.label if (match := first[data_type].match) else None,
            store=match.store if match else None,
            source=match.source if match else None,
        )
        for data_type, count in counts.items()
    ]
    for category in categories:
        if category.category in counts:
            continue
        counts[category.category] = 1
        match = category.match
        items.append(
            FoundItem(
                data_type=category.category,
                count=1,
                tier=category.tier,
                match_label=match.label if match else None,
                store=match.store if match else None,
                source=match.source if match else None,
            )
        )
    return items, dict(counts)


class Inspector:
    def __init__(self, detector: Detector, vault: Vault, policy: PolicyService) -> None:
        self._detector = detector
        self._vault = vault
        self._policy = policy

    async def inspect(
        self,
        *,
        principal: Principal,
        tool: ToolRef,
        conversation_id: str,
        vault_id: str,
        reading: Reading,
        channel: Channel = Channel.PROMPT,
    ) -> Inspection:
        """Inspect every text and name of one request. Raises `UninspectedError` for a name
        that holds a finding, before anything is masked. T2 and T3 classify the texts the
        user wrote."""
        started = time.perf_counter()
        timings: Counter[Tier] = Counter()
        texts = [slot.read() for slot in reading.texts]
        detected = [await self._detector.detect_local(text) for text in texts]
        timings.update(await self._read_names(reading.names))
        per_text: list[tuple[Finding, ...]] = []
        masked: list[MaskResult] = []
        for text, local in zip(texts, detected, strict=True):
            timings.update(local.timings_ms)
            kept = tuple(found for found in local.findings if not _CANARY.search(found.text))
            per_text.append(kept)
            masked.append(await self._vault.mask(vault_id, text, kept))
        findings = [finding for found_in_text in per_text for finding in found_in_text]
        contextual_text_indexes = [
            index for index, slot in enumerate(reading.texts) if slot.authored
        ]

        tiers_run: list[Tier] = [Tier.T0, Tier.T1]
        categories: tuple[CategoryFinding, ...] = ()
        usage = Usage()
        error: str | None = None
        if contextual_text_indexes:
            authored = "\n\n".join(masked[index].text for index in contextual_text_indexes)
            authored_findings = tuple(
                finding for index in contextual_text_indexes for finding in per_text[index]
            )
            contextual = await self._detector.detect_contextual(
                authored, local=LocalDetection(findings=authored_findings, timings_ms={})
            )
            timings.update(contextual.timings_ms)
            tiers_run.extend(contextual.tiers_run)
            categories, usage, error = contextual.categories, contextual.usage, contextual.error

        found, counts = summarise(findings, categories)
        context = PolicyContext(
            channel=channel,
            data_types=frozenset(counts),
            tool=tool.slug,
            tool_status=tool.status,
            team=principal.team,
            detector_error=error is not None,
        )
        return Inspection(
            trace_id=uuid4().hex,
            conversation_id=conversation_id,
            vault_id=vault_id,
            tool=tool,
            context=context,
            decision=await self._policy.decide(context, found),
            masked=tuple(masked),
            timings_ms=dict(timings),
            tiers_run=tuple(tiers_run),
            data_counts=counts,
            usage=usage,
            error=error,
            started=started,
        )

    async def _read_names(self, names: Sequence[Name]) -> Mapping[Tier, float]:
        """Run detection over the names, as one text. A name cannot carry a placeholder,
        so a finding in one refuses the request."""
        if not names:
            return {}
        local = await self._detector.detect_local(_NAME_BREAK.join(name.value for name in names))
        if local.findings:
            first = local.findings[0]
            ends = list(accumulate(len(name.value) + len(_NAME_BREAK) for name in names))
            name = names[bisect_right(ends, first.start)]
            raise UninspectedError(
                name.where, f"the gateway found {first.data_type} in it and cannot mask this field"
            )
        return local.timings_ms
