"""The stores as detection reads them: decrypted, in memory, immutable.

A reload builds a new `State` and swaps it in, so a request sees the stores either before
or after a change, never in between.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import numpy as np

from gateway.app.core.types import DataType, RowSource
from gateway.app.detect.fingerprint import BENIGN, DocumentInfo, FingerprintIndex
from gateway.app.detect.patterns import PatternRule
from gateway.app.detect.terms import TermRule
from gateway.app.llm.client import Matrix
from gateway.app.protected.crypto import TermCipher
from gateway.app.protected.models import CustomPattern, ProtectedDocument, ProtectedTerm

Scope = frozenset[RowSource] | None


@dataclass(frozen=True, slots=True)
class TermRow:
    id: UUID
    source: RowSource
    group: str
    data_type: str
    term: str
    aliases: tuple[str, ...]
    enabled: bool
    created: datetime

    @classmethod
    def read(cls, row: ProtectedTerm, cipher: TermCipher) -> "TermRow":
        return cls(
            id=row.id,
            source=RowSource(row.source),
            group=row.group_name,
            data_type=row.data_type,
            term=cipher.decrypt(row.term),
            aliases=cipher.decrypt_list(row.aliases),
            enabled=row.enabled,
            created=row.created,
        )

    @property
    def rule(self) -> TermRule:
        return TermRule(
            str(self.id), self.term, self.aliases, self.data_type, self.source, self.group
        )


@dataclass(frozen=True, slots=True)
class PatternRow:
    id: UUID
    source: RowSource
    group: str
    name: str
    regex: str
    data_type: str
    enabled: bool
    created: datetime

    @classmethod
    def read(cls, row: CustomPattern) -> "PatternRow":
        return cls(
            id=row.id,
            source=RowSource(row.source),
            group=row.group_name,
            name=row.name,
            regex=row.regex,
            data_type=row.data_type,
            enabled=row.enabled,
            created=row.created,
        )

    @property
    def rule(self) -> PatternRule:
        return PatternRule(
            str(self.id), self.name, self.regex, self.data_type, self.source, self.group
        )


@dataclass(frozen=True, slots=True)
class DocumentRow:
    id: UUID
    source: RowSource
    label: str
    category: str
    language: str | None
    chunks: int
    embedder_id: str
    stale: bool
    enabled: bool
    created: datetime

    @classmethod
    def read(cls, row: ProtectedDocument) -> "DocumentRow":
        return cls(
            id=row.id,
            source=RowSource(row.source),
            label=row.label,
            category=row.category,
            language=row.language,
            chunks=row.chunks,
            embedder_id=row.embedder_id,
            stale=row.stale,
            enabled=row.enabled,
            created=row.created,
        )

    @property
    def info(self) -> DocumentInfo:
        return DocumentInfo(str(self.id), self.label, self.category, self.source)


def _in_scope(source: RowSource, scope: Scope) -> bool:
    return scope is None or source in scope


@dataclass(frozen=True)
class State:
    terms: tuple[TermRow, ...] = ()
    patterns: tuple[PatternRow, ...] = ()
    documents: tuple[DocumentRow, ...] = ()
    vectors: dict[UUID, Matrix] = field(default_factory=dict)
    data_types: frozenset[str] = DataType.BUILT_IN

    def term_rules(self, scope: Scope) -> list[TermRule]:
        return [row.rule for row in self.terms if row.enabled and _in_scope(row.source, scope)]

    def pattern_rules(self, scope: Scope) -> list[PatternRule]:
        return [row.rule for row in self.patterns if row.enabled and _in_scope(row.source, scope)]

    def fingerprint_index(self, scope: Scope) -> FingerprintIndex:
        """Only documents with vectors in memory: enabled, current embedder, in scope."""
        infos: list[DocumentInfo] = []
        matrices: list[Matrix] = []
        owners: list[int] = []
        for row in self.documents:
            matrix = self.vectors.get(row.id)
            if matrix is None or not _in_scope(row.source, scope):
                continue
            owners += [len(infos)] * len(matrix)
            infos.append(row.info)
            matrices.append(matrix)
        stacked = np.vstack(matrices) if matrices else np.zeros((0, 0), dtype=np.float32)
        return FingerprintIndex(infos, stacked, owners)


def known_data_types(
    terms: Collection[TermRow], patterns: Collection[PatternRow], documents: Collection[DocumentRow]
) -> frozenset[str]:
    """Built-in types plus every type or category a company row introduced."""
    custom = (
        {row.data_type for row in terms}
        | {row.data_type for row in patterns}
        | {row.category for row in documents if row.category != BENIGN}
    )
    return DataType.BUILT_IN | custom
