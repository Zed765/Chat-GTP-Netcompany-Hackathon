"""T2: fingerprints of masked text. Documents are stored as chunk vectors only; a prompt is
chunked the same way and compared by cosine similarity, in process, with NumPy."""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from gateway.app.core.types import (
    CategoryFinding,
    DataType,
    Finding,
    RowSource,
    Store,
    StoreRef,
    Tier,
)
from gateway.app.llm.client import Matrix

CHUNK_TOKENS = 200
CHUNK_OVERLAP = 50
BENIGN = "BENIGN"

_PLACEHOLDER = re.compile(r"<([A-Z][A-Z0-9_]*?)_(?:\d+|REDACTED)>")
_CATEGORY_NAME = re.compile(r"[^A-Z0-9]+")
_DESCRIPTIONS = {
    DataType.CONTRACT: "a contract",
    DataType.FINANCIAL: "a financial document",
    DataType.HEALTH: "a health record",
    DataType.HR: "an HR document",
    DataType.SOURCE_CODE: "source code",
    DataType.CLIENT_CONFIDENTIAL: "a client-confidential document",
}


def normalise_category(name: str) -> str:
    """`source code` and `source-code` both become `SOURCE_CODE`."""
    return _CATEGORY_NAME.sub("_", name.strip().upper()).strip("_")


def describe(category: str) -> str:
    return _DESCRIPTIONS.get(category, f"a {category.lower().replace('_', ' ')} document")


def reduce_placeholders(text: str) -> str:
    """`<PERSON_3>` becomes `<PERSON>`, so the same document masked twice reads the same."""
    return _PLACEHOLDER.sub(r"<\1>", text)


def mask_by_type(text: str, findings: Sequence[Finding]) -> str:
    """Replace each maskable finding with its type. `findings` are sorted and disjoint."""
    parts: list[str] = []
    cursor = 0
    for finding in findings:
        if finding.maskable:
            parts += (text[cursor : finding.start], f"<{finding.data_type}>")
            cursor = finding.end
    parts.append(text[cursor:])
    return "".join(parts)


def token_count(text: str) -> int:
    return len(text.split())


def chunks(text: str, size: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Windows of `size` whitespace-separated tokens, each starting `size - overlap` later."""
    tokens = text.split()
    if not tokens:
        return []
    step = size - overlap
    last_start = max(0, len(tokens) - overlap - 1)
    return [" ".join(tokens[start : start + size]) for start in range(0, last_start + 1, step)]


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    row_id: str
    label: str
    category: str
    source: RowSource

    @property
    def ref(self) -> StoreRef:
        return StoreRef(
            store=Store.FINGERPRINTS, row_id=self.row_id, source=self.source, label=self.label
        )


@dataclass(frozen=True, slots=True)
class DocumentMatch:
    document: DocumentInfo
    similarity: float


@dataclass(frozen=True, slots=True)
class ExemplarVote:
    category: str
    similarity: float
    votes: int
    nearest: DocumentInfo


@dataclass(frozen=True, slots=True)
class FingerprintScores:
    """The raw T2 result before thresholds, which is what the evaluation tunes against."""

    document: DocumentMatch | None
    exemplars: ExemplarVote | None


class FingerprintIndex:
    """Chunk vectors of the enabled documents of one embedder. `owners[i]` is the index in
    `documents` of the document that row `i` of `vectors` came from."""

    def __init__(
        self, documents: Sequence[DocumentInfo], vectors: Matrix, owners: Sequence[int]
    ) -> None:
        self._documents = tuple(documents)
        self._vectors = vectors
        self._owners = np.asarray(owners, dtype=np.int64)
        is_exemplar = np.asarray(
            [document.source is RowSource.DEFAULT for document in self._documents], dtype=bool
        )
        self._exemplar_rows = is_exemplar[self._owners] if len(self._owners) else is_exemplar

    def __len__(self) -> int:
        return len(self._documents)

    def _best_per_document(self, query: Matrix, exemplars: bool) -> dict[int, float]:
        """For each document of the wanted layer, its best chunk-to-chunk similarity."""
        rows = np.flatnonzero(self._exemplar_rows == exemplars)
        if not len(rows) or not len(query):
            return {}
        best_per_row = (query @ self._vectors[rows].T).max(axis=0)
        best: dict[int, float] = {}
        for owner, similarity in zip(
            self._owners[rows].tolist(), best_per_row.tolist(), strict=True
        ):
            if similarity > best.get(owner, -1.0):
                best[owner] = similarity
        return best

    def best_document(self, query: Matrix) -> DocumentMatch | None:
        """The company document closest to any chunk of the prompt."""
        best = self._best_per_document(query, exemplars=False)
        if not best:
            return None
        owner = max(best, key=best.__getitem__)
        return DocumentMatch(self._documents[owner], best[owner])

    def exemplar_vote(self, query: Matrix, neighbours: int) -> ExemplarVote | None:
        """Majority category among the nearest exemplars; ties go to the closer group."""
        best = self._best_per_document(query, exemplars=True)
        nearest = sorted(best, key=best.__getitem__, reverse=True)[:neighbours]
        if not nearest:
            return None
        votes = Counter(self._documents[owner].category for owner in nearest)
        closeness: defaultdict[str, float] = defaultdict(float)
        for owner in nearest:
            closeness[self._documents[owner].category] += best[owner]
        category = max(votes, key=lambda name: (votes[name], closeness[name]))
        voters = [owner for owner in nearest if self._documents[owner].category == category]
        return ExemplarVote(
            category=category,
            similarity=closeness[category] / len(voters),
            votes=len(voters),
            nearest=self._documents[voters[0]],
        )

    def scores(self, query: Matrix, neighbours: int) -> FingerprintScores:
        return FingerprintScores(self.best_document(query), self.exemplar_vote(query, neighbours))


def to_findings(
    scores: FingerprintScores, document_threshold: float, exemplar_threshold: float
) -> CategoryFinding | None:
    """A company document above its threshold is conclusive and named. Otherwise the
    exemplars may say what kind of document the text resembles, which is not conclusive."""
    match = scores.document
    if match is not None and match.similarity >= document_threshold:
        return CategoryFinding(
            category=match.document.category,
            tier=Tier.T2,
            score=min(1.0, match.similarity),
            conclusive=True,
            match=match.document.ref,
            evidence=f'matches "{match.document.label}"',
        )
    vote = scores.exemplars
    if vote is None or vote.category == BENIGN or vote.similarity < exemplar_threshold:
        return None
    return CategoryFinding(
        category=vote.category,
        tier=Tier.T2,
        score=min(1.0, max(0.0, vote.similarity)),
        conclusive=False,
        match=None,
        evidence=f"resembles {describe(vote.category)}",
    )
