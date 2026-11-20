"""The arithmetic of the evaluation: matching findings to labels and turning counts into scores.

A label counts as found when findings of an acceptable type cover at least half of its
characters. A finding that touches no label it could stand for is a false positive.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from eval.schema import Score, TypeScore

MIN_COVERAGE = 0.5
CLIENT = "CLIENT"
NAME_TYPES = frozenset({"PERSON", "ORG"})
# Place names are not labelled, so a LOCATION is never an error; it only helps find an address.
UNSCORED_TYPES = frozenset({"LOCATION"})
NOT_A_CATEGORY = "BENIGN"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str
    is_client: bool = False

    def overlap(self, other: "Span") -> int:
        return max(0, min(self.end, other.end) - max(self.start, other.start))


def stands_for(finding: Span, label: Span) -> bool:
    """Whether a finding of this type may count as detecting that label."""
    if finding.type == label.type:
        return True
    if finding.type == CLIENT:
        return label.is_client
    return finding.type == "LOCATION" and label.type == "ADDRESS"


def is_found(label: Span, findings: Iterable[Span]) -> bool:
    covered = sum(f.overlap(label) for f in findings if stands_for(f, label))
    return covered >= MIN_COVERAGE * (label.end - label.start)


def make_score(true_positives: int, false_positives: int, false_negatives: int) -> Score:
    predicted = true_positives + false_positives
    actual = true_positives + false_negatives
    precision = true_positives / predicted if predicted else 0.0
    recall = true_positives / actual if actual else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Score(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


@dataclass
class Tally:
    """Counts per data type, added up sample by sample."""

    tp: Counter[str] = field(default_factory=Counter)
    fp: Counter[str] = field(default_factory=Counter)
    fn: Counter[str] = field(default_factory=Counter)

    def add_spans(self, labels: Sequence[Span], findings: Sequence[Span]) -> list[Span]:
        """Score one text. Returns the labels that were missed."""
        missed = []
        for label in labels:
            if is_found(label, findings):
                self.tp[label.type] += 1
            else:
                self.fn[label.type] += 1
                missed.append(label)
        for finding in findings:
            touched = [label for label in labels if finding.overlap(label)]
            if finding.type not in UNSCORED_TYPES | {CLIENT}:
                self.fp[finding.type] += not any(stands_for(finding, label) for label in touched)
        self._add_clients(labels, findings)
        return missed

    def _add_clients(self, labels: Sequence[Span], findings: Sequence[Span]) -> None:
        """`CLIENT` is scored on its own: was a client's name recognised as a client?"""
        named = [label for label in labels if label.is_client]
        claims = [finding for finding in findings if finding.type == CLIENT]
        for label in named:
            key = "tp" if is_found(label, claims) else "fn"
            getattr(self, key)[CLIENT] += 1
        self.fp[CLIENT] += sum(not any(c.overlap(label) for label in named) for c in claims)

    def add_categories(self, expected: Iterable[str], predicted: Iterable[str]) -> None:
        wanted = set(expected) - {NOT_A_CATEGORY}
        got = set(predicted) - {NOT_A_CATEGORY}
        for category in wanted | got:
            key = "tp" if category in wanted & got else "fn" if category in wanted else "fp"
            getattr(self, key)[category] += 1

    def types(self) -> list[str]:
        return sorted(set(self.tp) | set(self.fp) | set(self.fn))

    def overall(self) -> Score:
        """Everything except `CLIENT`, whose labels are already counted as PERSON or ORG."""
        types = [data_type for data_type in self.types() if data_type != CLIENT]
        return make_score(
            sum(self.tp[t] for t in types),
            sum(self.fp[t] for t in types),
            sum(self.fn[t] for t in types),
        )

    def by_type(self) -> list[TypeScore]:
        return [
            TypeScore(
                data_type=data_type,
                **make_score(
                    self.tp[data_type], self.fp[data_type], self.fn[data_type]
                ).model_dump(),
            )
            for data_type in self.types()
        ]


def percentile(values: Sequence[float], share: float) -> float:
    """Nearest-rank percentile; `share` is between 0 and 1."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * share // 1))
    return round(ordered[int(rank) - 1], 3)


def rate(hits: int, total: int) -> float:
    return round(hits / total, 4) if total else 0.0
