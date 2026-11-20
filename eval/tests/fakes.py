"""Stand-ins for the gateway's services, simple enough to predict every number by hand."""

import re
from collections.abc import Collection, Mapping, Sequence

from gateway.app.core.types import (
    Action,
    CategoryFinding,
    ContextualDetection,
    Explanation,
    Finding,
    FoundItem,
    InjectionProtection,
    InjectionVerdict,
    LocalDetection,
    MaskedSpan,
    MaskResult,
    PlaceholderInfo,
    PolicyContext,
    PolicyDecision,
    RehydrationReport,
    RowSource,
    Store,
    StoreRef,
    Tier,
    Trust,
    Usage,
)

PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")


class FakeDetector:
    """Finds the literal strings it is given. `hidden` ones are found only after
    normalisation; `categories` are returned when their marker is in the masked text, those
    of tier T3 only when the model may be asked."""

    def __init__(
        self,
        known: Mapping[str, tuple[str, Tier]],
        *,
        hidden: Mapping[str, str] | None = None,
        categories: Mapping[str, CategoryFinding] | None = None,
    ) -> None:
        self._known = dict(known)
        self._hidden = dict(hidden or {})
        self._categories = dict(categories or {})

    async def detect_local(self, text: str, normalise: bool = True) -> LocalDetection:
        literals = dict(self._known)
        if normalise:
            literals |= {literal: (kind, Tier.T0) for literal, kind in self._hidden.items()}
        findings = [
            Finding(
                data_type=kind,
                start=match.start(),
                end=match.end(),
                text=match.group(),
                tier=tier,
                score=1.0,
                recogniser="fake",
            )
            for literal, (kind, tier) in literals.items()
            for match in re.finditer(re.escape(literal), text)
        ]
        ordered = tuple(sorted(findings, key=lambda finding: finding.start))
        return LocalDetection(findings=ordered, timings_ms={Tier.T0: 1.0, Tier.T1: 3.0})

    async def detect_contextual(
        self,
        masked_text: str,
        *,
        local: LocalDetection,
        force_t3: bool = False,
        use_model: bool = True,
    ) -> ContextualDetection:
        found = [finding for marker, finding in self._categories.items() if marker in masked_text]
        tiers = (Tier.T2, Tier.T3) if use_model else (Tier.T2,)
        return ContextualDetection(
            categories=tuple(finding for finding in found if finding.tier in tiers),
            timings_ms={Tier.T2: 10.0},
            tiers_run=tiers,
            usage=Usage(cost_usd=0.002 if use_model else 0.0),
        )


def company_document(category: str = "CONTRACT") -> CategoryFinding:
    match = StoreRef(store=Store.FINGERPRINTS, row_id="1", source=RowSource.SEEDED, label="MSA")
    return CategoryFinding(
        category=category, tier=Tier.T2, score=0.9, conclusive=True, match=match, evidence="matches"
    )


def resembles(category: str, tier: Tier = Tier.T2, score: float = 0.6) -> CategoryFinding:
    return CategoryFinding(
        category=category, tier=tier, score=score, conclusive=False, evidence="resembles"
    )


class _Rehydrator:
    def __init__(self, values: Mapping[str, str], sent: Collection[str]) -> None:
        self._values = values
        self._sent = set(sent)
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        return ""

    def flush(self) -> str:
        return PLACEHOLDER.sub(lambda m: self._values.get(m.group(), m.group()), self._buffer)

    def report(self) -> RehydrationReport:
        seen = set(PLACEHOLDER.findall(self._buffer))
        return RehydrationReport(
            sent=len(self._sent),
            returned=len(seen & self._sent),
            unresolved=tuple(sorted(seen - set(self._values))),
        )


class FakeVault:
    def __init__(self) -> None:
        self._values: dict[str, dict[str, str]] = {}

    async def mask(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> MaskResult:
        values = self._values.setdefault(conversation_id, {})
        spans = []
        masked = text
        for number, finding in reversed(list(enumerate(findings, 1))):
            placeholder = f"<{finding.data_type}_{number}>"
            values[placeholder] = finding.text
            masked = masked[: finding.start] + placeholder + masked[finding.end :]
            spans.append(
                MaskedSpan(
                    start=finding.start,
                    end=finding.end,
                    placeholder=placeholder,
                    data_type=finding.data_type,
                    tier=finding.tier,
                    recogniser=finding.recogniser,
                )
            )
        return MaskResult(text=masked, spans=tuple(reversed(spans)))

    async def rehydrator(self, conversation_id: str, sent: Collection[str]) -> _Rehydrator:
        return _Rehydrator(self._values.get(conversation_id, {}), sent)

    async def resolve(self, conversation_id: str, text: str) -> tuple[str, RehydrationReport]:
        rehydrator = await self.rehydrator(conversation_id, PLACEHOLDER.findall(text))
        rehydrator.feed(text)
        return rehydrator.flush(), rehydrator.report()

    async def describe(self, conversation_id: str) -> list[PlaceholderInfo]:
        return []

    async def end(self, conversation_id: str) -> None:
        self._values.pop(conversation_id, None)


class FakeInjection:
    """Flags content that contains one of its trigger words. `off` never flags."""

    def __init__(self, *triggers: str) -> None:
        self._triggers = triggers

    async def inspect(
        self, content: str, *, source: Trust, level: InjectionProtection
    ) -> InjectionVerdict:
        on = level != InjectionProtection.OFF
        flagged = on and any(trigger in content.lower() for trigger in self._triggers)
        return InjectionVerdict(flagged=flagged, confidence=1.0 if flagged else 0.0)


class FakePolicy:
    """The agent rules of the default policy: tainted side effects are blocked, untrusted
    destinations get placeholders, everything else is allowed."""

    version = 1
    injection_protection = InjectionProtection.STANDARD

    async def decide(self, ctx: PolicyContext, found: Sequence[FoundItem]) -> PolicyDecision:
        if ctx.tainted and ctx.side_effects:
            action, rule = Action.BLOCK, "tainted-agent-side-effects"
        elif ctx.destination == Trust.UNTRUSTED:
            action, rule = Action.REDACT, "untrusted-destinations-get-placeholders"
        else:
            action, rule = Action.ALLOW, "default"
        explanation = Explanation(summary=rule, found=tuple(found), rule=rule, action=action)
        return PolicyDecision(
            action=action, rule=rule, policy_version=1, matched_types=(), explanation=explanation
        )
