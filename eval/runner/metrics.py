"""The plan's metrics, each computed on the held-out split with the services in a `Toolkit`."""

import time
from collections import Counter, defaultdict
from collections.abc import Sequence

from eval.runner.harness import Detector, Layers, Notebook, Toolkit, conversation
from eval.runner.samples import (
    AgentScenario,
    CategorySample,
    DlpSample,
    EvasionSample,
    FingerprintSample,
    InjectionSample,
)
from eval.runner.scoring import NOT_A_CATEGORY, Span, Tally, is_found, make_score, percentile, rate
from eval.schema import (
    AgentScenarioResult,
    CategoryScore,
    DetectionResult,
    EvasionResult,
    FingerprintScore,
    InjectionScore,
    LatencyRow,
    TechniqueRecall,
    TierScore,
)
from gateway.app.core.types import (
    Action,
    CategoryFinding,
    Channel,
    ContextualDetection,
    Finding,
    FoundItem,
    InjectionProtection,
    LocalDetection,
    PolicyContext,
    RowSource,
    Store,
    Tier,
    Trust,
)

TIER_STEPS = ((Tier.T0,), (Tier.T0, Tier.T1), (Tier.T0, Tier.T1, Tier.T2), tuple(Tier))
LEVELS = {
    "layer 1": InjectionProtection.STANDARD,
    "layer 1 + layer 2": InjectionProtection.DETAILED,
}


def _spans(findings: Sequence[Finding], tiers: Sequence[Tier] = tuple(Tier)) -> list[Span]:
    return [Span(f.start, f.end, f.data_type) for f in findings if f.tier in tiers]


async def _inspect(
    detector: Detector,
    toolkit: Toolkit,
    text: str,
    *,
    force_t3: bool = False,
    use_model: bool = True,
) -> tuple[LocalDetection, ContextualDetection]:
    """Both passes of detection, the second on the masked text as in the prompt path.
    `use_model=False` stops at T2, which is how T2 is measured on its own."""
    scope = conversation()
    local = await detector.detect_local(text)
    masked = await toolkit.vault.mask(scope, text, local.findings)
    contextual = await detector.detect_contextual(
        masked.text, local=local, force_t3=force_t3, use_model=use_model
    )
    await toolkit.vault.end(scope)
    return local, contextual


async def detection(
    toolkit: Toolkit, layers: Layers, samples: Sequence[DlpSample], notebook: Notebook
) -> DetectionResult:
    detector = toolkit.detectors[layers]
    tallies = {tiers: Tally() for tiers in TIER_STEPS}
    for sample in samples:
        # T3 replaces what T2 found, so T2's own answer is asked for separately.
        _, up_to_t2 = await _inspect(detector, toolkit, sample.text, use_model=False)
        local, contextual = await _inspect(detector, toolkit, sample.text)
        notebook.time(local.timings_ms)
        notebook.time(contextual.timings_ms)
        notebook.cost_usd += contextual.usage.cost_usd
        notebook.prompts_costed += 1
        labels = [label.span() for label in sample.labels]
        for tiers, tally in tallies.items():
            missed = tally.add_spans(labels, _spans(local.findings, tiers))
            judged = contextual if Tier.T3 in tiers else up_to_t2
            found = [c.category for c in judged.categories if c.tier in tiers]
            tally.add_categories(sample.categories, found)
            if tiers == TIER_STEPS[-1]:
                _note_errors(notebook, layers, sample, missed, local.findings, found)
    full = tallies[TIER_STEPS[-1]]
    return DetectionResult(
        layers=layers,
        overall=full.overall(),
        by_type=full.by_type(),
        by_tier=[
            TierScore(tiers="+".join(tiers), **tally.overall().model_dump())
            for tiers, tally in tallies.items()
        ],
    )


def _note_errors(
    notebook: Notebook,
    layers: Layers,
    sample: DlpSample,
    missed: Sequence[Span],
    findings: Sequence[Finding],
    categories: Sequence[str],
) -> None:
    for label in missed:
        value = sample.text[label.start : label.end]
        note = f"{layers}: missed {value!r}"
        notebook.miss("dlp", sample.id, "false_negative", label.type, sample.text, note)
    labels = [label.span() for label in sample.labels]
    for finding in findings:
        span = Span(finding.start, finding.end, finding.data_type)
        if finding.data_type != "LOCATION" and not any(span.overlap(label) for label in labels):
            note = f"{layers}: {finding.recogniser} flagged {finding.text!r}"
            notebook.miss("dlp", sample.id, "false_positive", finding.data_type, sample.text, note)
    for category in set(categories) - set(sample.categories) - {NOT_A_CATEGORY}:
        note = f"{layers}: classified as {category}"
        notebook.miss("dlp", sample.id, "false_positive", category, sample.text, note)


async def evasion(
    toolkit: Toolkit, samples: Sequence[EvasionSample], notebook: Notebook
) -> EvasionResult:
    """Recall on obfuscated values, with the normalisation step and without it."""
    detector = toolkit.best_detector
    found: dict[bool, Counter[str]] = {True: Counter(), False: Counter()}
    totals: Counter[str] = Counter()
    for sample in samples:
        for normalise in (True, False):
            spans = [
                _spans((await detector.detect_local(turn, normalise=normalise)).findings)
                for turn in sample.turns
            ]
            for label in sample.labels:
                hit = is_found(label.span(), spans[label.turn])
                found[normalise][sample.technique] += hit
                if normalise:
                    totals[sample.technique] += 1
                    if not hit:
                        note = f"{sample.technique}: missed {label.text!r}"
                        text = "\n".join(sample.turns)
                        notebook.miss(
                            "evasion", sample.id, "false_negative", label.type, text, note
                        )
    labels = sum(totals.values())
    return EvasionResult(
        samples=len(samples),
        recall_with_normalisation=rate(sum(found[True].values()), labels),
        recall_without_normalisation=rate(sum(found[False].values()), labels),
        by_technique=[
            TechniqueRecall(
                technique=technique,
                samples=total,
                recall_with_normalisation=rate(found[True][technique], total),
                recall_without_normalisation=rate(found[False][technique], total),
            )
            for technique, total in sorted(totals.items())
        ],
    )


def _matches_company_document(finding: CategoryFinding) -> bool:
    match = finding.match
    return (
        finding.conclusive
        and match is not None
        and match.store == Store.FINGERPRINTS
        and match.source != RowSource.DEFAULT
    )


async def fingerprint(
    toolkit: Toolkit, samples: Sequence[FingerprintSample], notebook: Notebook
) -> list[FingerprintScore]:
    """Does T2 recognise an excerpt of a protected document, and leave other documents alone?"""
    detector = toolkit.detectors["default+demo"]
    hits: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    for sample in samples:
        _, contextual = await _inspect(detector, toolkit, sample.text)
        notebook.time(contextual.timings_ms)
        flagged = any(_matches_company_document(c) for c in contextual.categories)
        totals[sample.variant] += 1
        hits[sample.variant] += flagged
        if flagged != (sample.variant != "negative"):
            kind = "false_positive" if flagged else "false_negative"
            note = (
                f"{sample.variant} excerpt of {sample.source_document or 'no protected document'}"
            )
            notebook.miss("fingerprint", sample.id, kind, "FINGERPRINT", sample.text, note)
    false_positives = hits["negative"]
    variants = [name for name in totals if name != "negative"]
    scores = [
        (name, make_score(hits[name], false_positives, totals[name] - hits[name]))
        for name in sorted(variants)
    ]
    positives = sum(totals[name] for name in variants)
    found = sum(hits[name] for name in variants)
    scores.append(("all", make_score(found, false_positives, positives - found)))
    return [
        FingerprintScore.model_validate(
            {"embedder": toolkit.embedder_id, "variant": name, **score.model_dump()}
        )
        for name, score in scores
    ]


def _top_category(contextual: ContextualDetection, tier: Tier) -> str:
    found = [c for c in contextual.categories if c.tier == tier]
    return max(found, key=lambda c: c.score).category if found else NOT_A_CATEGORY


async def category(
    toolkit: Toolkit, layers: Layers, samples: Sequence[CategorySample], notebook: Notebook
) -> list[CategoryScore]:
    """Document-category accuracy of the T2 exemplars on their own, and of T3."""
    detector = toolkit.detectors[layers]
    correct: dict[Tier, int] = defaultdict(int)
    for sample in samples:
        _, up_to_t2 = await _inspect(detector, toolkit, sample.text, use_model=False)
        _, contextual = await _inspect(detector, toolkit, sample.text, force_t3=True)
        for tier, judged in ((Tier.T2, up_to_t2), (Tier.T3, contextual)):
            predicted = _top_category(judged, tier)
            correct[tier] += predicted == sample.category
            if tier == Tier.T2 and predicted != sample.category:
                kind = "false_negative" if predicted == NOT_A_CATEGORY else "false_positive"
                note = f"{layers}: T2 said {predicted}, the label is {sample.category}"
                notebook.miss("category", sample.id, kind, sample.category, sample.text, note)
    return [
        CategoryScore(
            method=method,
            layers=layers,
            accuracy=rate(correct[tier], len(samples)),
            samples=len(samples),
        )
        for method, tier in (("T2 exemplars", Tier.T2), ("T3", Tier.T3))
    ]


async def injection(
    toolkit: Toolkit, samples: Sequence[InjectionSample], notebook: Notebook
) -> list[InjectionScore]:
    scores = []
    baseline: float | None = None
    for name, detector in toolkit.injection.items():
        counts: Counter[str] = Counter()
        elapsed = []
        for sample in samples:
            started = time.perf_counter()
            verdict = await detector.inspect(
                sample.text, source=Trust.UNTRUSTED, level=LEVELS[name]
            )
            elapsed.append((time.perf_counter() - started) * 1000)
            attack = sample.label == "injection"
            counts["tp" if attack else "fp"] += verdict.flagged
            counts["fn"] += attack and not verdict.flagged
            if verdict.flagged != attack:
                kind = "false_negative" if attack else "false_positive"
                note = f"{name}: {sample.technique} in a {sample.carrier}"
                notebook.miss("injection", sample.id, kind, "INJECTION", sample.text, note)
        median = percentile(elapsed, 0.5)
        added = None if baseline is None else round(median - baseline, 3)
        baseline = median if baseline is None else baseline
        score = make_score(counts["tp"], counts["fp"], counts["fn"])
        scores.append(
            InjectionScore.model_validate(
                {"layers": name, "added_latency_ms_p50": added, **score.model_dump()}
            )
        )
    notebook.skipped.append("injection layer 2 cost: a verdict carries no model usage")
    return scores


async def agent_scenarios(
    toolkit: Toolkit, scenarios: Sequence[AgentScenario]
) -> list[AgentScenarioResult]:
    """Replay each attack at the gateway's decision points: what the agent reads is inspected,
    then the side-effect call it would make is put to the policy."""
    results = []
    for scenario in scenarios:
        scope = conversation()
        local = await toolkit.best_detector.detect_local(scenario.record)
        masked = await toolkit.vault.mask(scope, scenario.record, local.findings)
        await toolkit.vault.end(scope)
        types = Counter(finding.data_type for finding in local.findings)
        found = [FoundItem(data_type=t, count=n, tier=Tier.T0) for t, n in types.items()]
        for level in InjectionProtection:
            name = "layer 1 + layer 2" if level == InjectionProtection.DETAILED else "layer 1"
            verdict = await toolkit.injection[name].inspect(
                scenario.content, source=Trust.UNTRUSTED, level=level
            )
            context = PolicyContext(
                channel=Channel.TOOL_CALL,
                data_types=frozenset(types),
                tool=scenario.tool,
                # Untrusted content taints the session unless protection is off.
                tainted=level != InjectionProtection.OFF,
                side_effects=scenario.side_effects,
                destination=Trust(scenario.destination),
            )
            decision = await toolkit.policy.decide(context, found)
            sent = scenario.record if decision.action == Action.ALLOW else masked.text
            reaches_outsider = (
                scenario.destination == "untrusted" and decision.action != Action.BLOCK
            )
            results.append(
                AgentScenarioResult(
                    scenario=scenario.id,
                    protection=level.value,
                    flagged=verdict.flagged,
                    side_effect_blocked=decision.action == Action.BLOCK,
                    real_values_leaked=sum(value in sent for value in scenario.values)
                    if reaches_outsider
                    else 0,
                )
            )
    return results


def latency(notebook: Notebook) -> list[LatencyRow]:
    return [
        LatencyRow(
            tier=tier.value,
            p50_ms=percentile(samples, 0.5),
            p95_ms=percentile(samples, 0.95),
            samples=len(samples),
        )
        for tier, samples in sorted(notebook.timings.items())
    ]
