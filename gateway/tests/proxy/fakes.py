"""Small stand-ins for the modules the prompt path talks to."""

import re
from collections.abc import Collection, Sequence
from typing import ClassVar

from gateway.app.core.interfaces import Rehydrator
from gateway.app.core.types import (
    Action,
    ContextualDetection,
    Explanation,
    Finding,
    FoundItem,
    InjectionProtection,
    LocalDetection,
    MaskedSpan,
    MaskResult,
    PlaceholderInfo,
    PolicyContext,
    PolicyDecision,
    RehydrationReport,
    Tier,
    ToolRef,
    ToolStatus,
)
from gateway.app.events.writer import EventRecord

PATTERNS = {
    "AFM": re.compile(r"\b\d{9}\b"),
    "IBAN": re.compile(r"\bGR\d{25}\b"),
    "PERSON": re.compile(r"Maria Papadopoulou|Μαρία Παπαδοπούλου"),
    "SECRET": re.compile(r"sk-test-[a-z0-9]{8}"),
}
PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
HOLD_BACK = 32


class FakeDetector:
    async def detect_local(self, text: str) -> LocalDetection:
        findings = sorted(
            (
                Finding(
                    data_type=data_type,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(),
                    tier=Tier.T0,
                    score=1.0,
                    recogniser="fake",
                )
                for data_type, pattern in PATTERNS.items()
                for match in pattern.finditer(text)
            ),
            key=lambda finding: finding.start,
        )
        return LocalDetection(findings=tuple(findings), timings_ms={Tier.T0: 0.1, Tier.T1: 0.2})

    async def detect_contextual(
        self,
        masked_text: str,
        *,
        local: LocalDetection,
        force_t3: bool = False,
        use_model: bool = True,
    ) -> ContextualDetection:
        return ContextualDetection(categories=(), timings_ms={Tier.T2: 0.3}, tiers_run=(Tier.T2,))

    async def detect_contextual_many(
        self, masked_texts: Sequence[str], *, use_model: bool = True
    ) -> list[ContextualDetection]:
        return [
            ContextualDetection(categories=(), timings_ms={Tier.T2: 0.3}, tiers_run=(Tier.T2,))
            for _ in masked_texts
        ]


class _FakeRehydrator:
    def __init__(self, values: dict[str, str], sent: Collection[str]) -> None:
        self._values = values
        self._sent = len(sent)
        self._buffer = ""
        self._returned: set[str] = set()

    def _restore(self, text: str) -> str:
        def swap(match: re.Match[str]) -> str:
            if match.group() in self._values:
                self._returned.add(match.group())
            return self._values.get(match.group(), match.group())

        return PLACEHOLDER.sub(swap, text)

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        cut = self._buffer.rfind("<")
        if cut == -1 or ">" in self._buffer[cut:] or len(self._buffer) - cut > HOLD_BACK:
            cut = len(self._buffer)
        ready, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return self._restore(ready)

    def flush(self) -> str:
        ready, self._buffer = self._buffer, ""
        return self._restore(ready)

    def report(self) -> RehydrationReport:
        return RehydrationReport(sent=self._sent, returned=len(self._returned))


class FakeVault:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}

    async def mask(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> MaskResult:
        held = self.values.setdefault(conversation_id, {})
        by_value = {value: token for token, value in held.items()}
        spans: list[MaskedSpan] = []
        for finding in findings:
            token = by_value.get(finding.text)
            if token is None:
                number = sum(t.startswith(f"<{finding.data_type}_") for t in held) + 1
                token = f"<{finding.data_type}_{number}>"
                held[token] = by_value[finding.text] = finding.text
            spans.append(
                MaskedSpan(
                    start=finding.start,
                    end=finding.end,
                    placeholder=token,
                    data_type=finding.data_type,
                    tier=finding.tier,
                    recogniser=finding.recogniser,
                )
            )
        masked = text
        for span in reversed(spans):
            masked = masked[: span.start] + span.placeholder + masked[span.end :]
        return MaskResult(text=masked, spans=tuple(spans))

    async def rehydrator(self, conversation_id: str, sent: Collection[str]) -> Rehydrator:
        return _FakeRehydrator(self.values.get(conversation_id, {}), sent)

    async def resolve(self, conversation_id: str, text: str) -> tuple[str, RehydrationReport]:
        rehydrator = _FakeRehydrator(self.values.get(conversation_id, {}), ())
        return rehydrator.feed(text) + rehydrator.flush(), rehydrator.report()

    async def describe(self, conversation_id: str) -> list[PlaceholderInfo]:
        return []

    async def end(self, conversation_id: str) -> None:
        self.values.pop(conversation_id, None)


class FakePolicy:
    """Secrets block; anything else sensitive is redacted, warned about or allowed by status."""

    BY_STATUS: ClassVar = {
        ToolStatus.UNAPPROVED: Action.REDACT,
        ToolStatus.TOLERATED: Action.WARN,
        ToolStatus.APPROVED: Action.ALLOW,
    }

    @property
    def version(self) -> int:
        return 7

    @property
    def injection_protection(self) -> InjectionProtection:
        return InjectionProtection.STANDARD

    async def decide(self, ctx: PolicyContext, found: Sequence[FoundItem]) -> PolicyDecision:
        if "SECRET" in ctx.data_types:
            action, rule = Action.BLOCK, "secrets-never-leave"
        elif ctx.data_types and ctx.tool_status:
            action, rule = self.BY_STATUS[ctx.tool_status], "pii-and-client-data"
        else:
            action, rule = Action.ALLOW, "default"
        return PolicyDecision(
            action=action,
            rule=rule,
            policy_version=self.version,
            matched_types=tuple(sorted(ctx.data_types)),
            explanation=Explanation(
                summary=f"{action.value}: {len(found)} kinds of data",
                found=tuple(found),
                rule=rule,
                action=action,
            ),
        )


class FakeInventory:
    STATUS: ClassVar = {
        "chatterbox-ai": ToolStatus.UNAPPROVED,
        "draftpilot": ToolStatus.TOLERATED,
        "athena-assist": ToolStatus.APPROVED,
        "echo": ToolStatus.UNAPPROVED,
    }

    async def resolve(self, tool: str) -> ToolRef:
        return ToolRef(
            slug=tool,
            name=tool,
            status=self.STATUS.get(tool, ToolStatus.UNKNOWN),
            upstream_url=f"http://mock-upstream/tools/{tool}/v1" if tool in self.STATUS else None,
        )

    async def approved_alternatives(self, category: str | None) -> list[ToolRef]:
        return []


class FakeEvents:
    def __init__(self) -> None:
        self.records: list[EventRecord] = []
        self.acknowledged: list[str] = []

    async def write(self, record: EventRecord) -> int:
        self.records.append(record)
        return len(self.records)

    async def mark_forwarded(self, trace_id: str, user_id: str) -> bool:
        known = any(record.trace_id == trace_id for record in self.records)
        if known:
            self.acknowledged.append(trace_id)
        return known
