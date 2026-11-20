"""T0 and T1 in one synchronous engine: normalise, decode, recognise, settle overlaps.

The engine is immutable once built. A change to the protected stores builds a new one, so
a request never sees a half-updated set of terms or patterns.
"""

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from gateway.app.core.types import DataType, Finding, LocalDetection, Tier
from gateway.app.detect.companies import find_companies
from gateway.app.detect.encodings import decoded_runs
from gateway.app.detect.entropy import find_high_entropy
from gateway.app.detect.identifiers import find_identifiers
from gateway.app.detect.names import find_people, is_internal_unit, is_misread_person
from gateway.app.detect.ner import NerEngine
from gateway.app.detect.normalise import NormalisedText, normalise
from gateway.app.detect.patterns import PatternMatcher, PatternRule
from gateway.app.detect.spans import Span, resolve_overlaps, severity
from gateway.app.detect.terms import TermMatcher, TermRule
from gateway.app.detect.tokens import tokenise

MAX_DECODE_DEPTH = 2
MIN_SCORE = 0.5
# Bounds on the costly steps, so that no text, however long or contrived, can hold a
# worker for seconds. Checksums, patterns and terms are linear and read the whole text.
MAX_DECODED_RUNS = 100
MAX_MODEL_CHARS = 10_000
MIN_MODEL_CHARGE = 200


class _Clock:
    def __init__(self) -> None:
        self.elapsed: defaultdict[Tier, float] = defaultdict(float)
        self._tier: Tier | None = None
        self._started = 0.0

    def switch(self, tier: Tier | None) -> None:
        now = time.perf_counter()
        if self._tier is not None:
            self.elapsed[self._tier] += (now - self._started) * 1000
        self._tier, self._started = tier, now


class _ModelBudget:
    """How much text the language models may still read for one detection."""

    def __init__(self) -> None:
        self.left = MAX_MODEL_CHARS
        self.exhausted = False

    def take(self, text: str) -> str:
        """The part of `text` the models may read. Every call costs a minimum, because
        the models have a fixed cost per call however short the text."""
        allowed = text[: max(0, self.left)]
        self.exhausted = self.exhausted or len(allowed) < len(text)
        self.left -= max(len(allowed), MIN_MODEL_CHARGE)
        return allowed


class LocalEngine:
    def __init__(
        self, patterns: Sequence[PatternRule], terms: Sequence[TermRule], ner: NerEngine | None
    ) -> None:
        self._patterns = PatternMatcher(patterns)
        self._terms = TermMatcher(terms)
        self._ner = ner

    def detect(self, text: str, *, normalise_text: bool = True) -> LocalDetection:
        """`normalise_text=False` reads the text as typed: nothing stripped, nothing decoded."""
        clock = _Clock()
        clock.switch(Tier.T0)
        normalised = normalise(text) if normalise_text else NormalisedText(text)
        notes: list[str] = []
        depth = 0 if normalise_text else MAX_DECODE_DEPTH
        budget = _ModelBudget()
        spans = resolve_overlaps(self._scan(normalised.text, depth, clock, notes, budget))
        if budget.exhausted and self._ner is not None:
            notes.append(
                f"The text is long: names were recognised by the language models in its "
                f"first {MAX_MODEL_CHARS:,} characters only"
            )
        findings = tuple(_finding(text, normalised, span) for span in spans)
        clock.switch(None)
        return LocalDetection(
            findings=findings,
            timings_ms={tier: round(clock.elapsed[tier], 3) for tier in (Tier.T0, Tier.T1)},
            notes=tuple(notes),
        )

    def _scan(
        self, text: str, depth: int, clock: _Clock, notes: list[str], budget: _ModelBudget
    ) -> list[Span]:
        clock.switch(Tier.T0)
        runs = list(decoded_runs(text)) if depth < MAX_DECODE_DEPTH else []
        spans = [
            *find_identifiers(text),
            *self._patterns.find(text),
            *find_high_entropy(text, [(run.start, run.end) for run in runs]),
        ]
        clock.switch(Tier.T1)
        tokens = tokenise(text)
        gazetteer = self._terms.gazetteer
        candidates = self._ner.find(budget.take(text)) if self._ner is not None else []
        people = [
            span
            for span in candidates
            if span.data_type == DataType.PERSON or is_misread_person(span, tokens, gazetteer)
        ]
        spans += self._terms.find(text, tokens)
        spans += find_people(text, tokens, gazetteer, people)
        spans += find_companies(text, tokens)
        spans += [
            span for span in candidates if span not in people and not is_internal_unit(span, tokens)
        ]
        spans = [span for span in spans if span.score >= MIN_SCORE]
        if len(runs) > MAX_DECODED_RUNS:
            notes.append(f"Only the first {MAX_DECODED_RUNS} encoded runs were decoded")
        for run in runs[:MAX_DECODED_RUNS]:
            inner = resolve_overlaps(self._scan(run.text, depth + 1, clock, notes, budget))
            if inner:
                worst = min(inner, key=severity)
                spans.append(replace(worst, start=run.start, end=run.end, encoded=True))
                found = ", ".join(sorted({span.data_type for span in inner}))
                notes.append(f"Text encoded as {run.encoding} contained: {found}")
        return spans


def _finding(original: str, normalised: NormalisedText, span: Span) -> Finding:
    start, end = normalised.original_span(span.start, span.end)
    return Finding(
        data_type=span.data_type,
        start=start,
        end=end,
        text=original[start:end],
        tier=span.tier,
        score=span.score,
        recogniser=span.recogniser,
        match=span.match,
        canonical=span.canonical,
        encoded=span.encoded,
        maskable=span.maskable,
    )
