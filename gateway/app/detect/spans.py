"""Candidate spans in normalised-text coordinates, and the rule that settles overlaps."""

from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass

from gateway.app.core.types import DataType, RowSource, StoreRef, Tier

# Which type names an encoded run that holds several findings: the most severe first.
SEVERITY = (
    DataType.SECRET,
    DataType.CARD,
    DataType.IBAN,
    DataType.AMKA,
    DataType.AFM,
    DataType.ID_CARD,
    DataType.CLIENT,
    DataType.PERSON,
    DataType.EMAIL,
    DataType.PHONE,
    DataType.ADDRESS,
    DataType.ORG,
    DataType.LOCATION,
    DataType.CONFIDENTIAL_MARKER,
)


@dataclass(frozen=True, slots=True)
class Span:
    data_type: str
    start: int
    end: int
    tier: Tier
    score: float
    recogniser: str
    match: StoreRef | None = None
    canonical: str | None = None
    encoded: bool = False
    maskable: bool = True

    @property
    def from_company(self) -> bool:
        return self.match is not None and self.match.source is not RowSource.DEFAULT


def severity(span: Span) -> int:
    """Lower is more severe. Company-defined types rank with `CLIENT`."""
    if span.data_type in SEVERITY:
        return SEVERITY.index(span.data_type)
    return SEVERITY.index(DataType.CLIENT)


def _precedence(span: Span) -> tuple[int, int, int, int, float, int]:
    """Sort key: who keeps the text when two spans overlap.

    Encoded runs first (they hide everything inside), then checksum and pattern matches,
    then company terms, then default-pack terms, then statistical name recognition.
    Within a class the longer span wins, then a secret (it is blocked, not masked), and
    a company row beats a default row.
    """
    if span.encoded:
        klass = 0
    elif span.tier is Tier.T0:
        klass = 1
    elif span.from_company:
        klass = 2
    elif span.match is not None:
        klass = 3
    else:
        klass = 4
    secret = 0 if span.data_type == DataType.SECRET else 1
    company = 0 if span.from_company else 1
    return (klass, span.start - span.end, secret, company, -span.score, span.start)


def resolve_overlaps(spans: Iterable[Span]) -> list[Span]:
    """The spans that survive, sorted by start and never overlapping."""
    kept: list[Span] = []
    starts: list[int] = []
    for span in sorted(spans, key=_precedence):
        # The kept spans are disjoint and sorted, so only the two neighbours can overlap.
        at = bisect_left(starts, span.start)
        clear_before = at == 0 or kept[at - 1].end <= span.start
        clear_after = at == len(kept) or kept[at].start >= span.end
        if clear_before and clear_after:
            kept.insert(at, span)
            starts.insert(at, span.start)
    return kept
