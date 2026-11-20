"""The three protected-data stores: terms (T1), document fingerprints (T2), patterns (T0).

Every change is written to Postgres, then announced on the reload bus, so the next request
on any worker detects with the new rows.
"""

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import numpy as np
from cryptography.exceptions import InvalidTag
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.deps import Deps
from gateway.app.core.types import DataType, RowSource, Store
from gateway.app.detect.fingerprint import FingerprintIndex
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.ner import NerEngine
from gateway.app.detect.patterns import PatternError, compile_pattern
from gateway.app.llm.client import Matrix
from gateway.app.protected import defaults
from gateway.app.protected.crypto import TermCipher
from gateway.app.protected.documents import fingerprint
from gateway.app.protected.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    TooLargeError,
)
from gateway.app.protected.extract import MAX_DOCUMENT_BYTES, extract_text
from gateway.app.protected.imports import NewTerm, document_category, span_type, validate_rows
from gateway.app.protected.models import (
    CustomPattern,
    FingerprintChunk,
    ProtectedDocument,
    ProtectedTerm,
)
from gateway.app.protected.pack import (
    Exemplar,
    content_version,
    load_exemplars,
    load_pattern_pack,
    load_term_pack,
)
from gateway.app.protected.schemas import (
    DocumentOut,
    DocumentUploadResult,
    GroupOut,
    ImportResult,
    LayerCount,
    PatternIn,
    PatternOut,
    ProtectedSummary,
    RemoveDemoResult,
    StoreSummary,
    TermOut,
    TermPage,
)
from gateway.app.protected.state import (
    DocumentRow,
    PatternRow,
    Scope,
    State,
    TermRow,
    known_data_types,
)
from gateway.app.protected.term_source import CrmTermSource, TermSource

log = logging.getLogger(__name__)

TOPIC = "protected"
CUSTOM_PATTERN_GROUP = "custom"
_PACK_LOCK = 741_002
_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_LATIN = re.compile(r"[A-Za-z]")

Row = ProtectedTerm | CustomPattern | ProtectedDocument


async def _get(session: AsyncSession, store: Store, row_id: UUID) -> Row:
    row: Row | None
    if store is Store.TERMS:
        row = await session.get(ProtectedTerm, row_id)
    elif store is Store.PATTERNS:
        row = await session.get(CustomPattern, row_id)
    else:
        row = await session.get(ProtectedDocument, row_id)
    if row is None:
        raise NotFoundError("There is no such row")
    return row


async def _default_group(session: AsyncSession, store: Store, group: str) -> Sequence[Row]:
    """The default-pack rows of one group. Fingerprints are grouped by category."""
    if store is Store.TERMS:
        terms = select(ProtectedTerm).where(
            ProtectedTerm.source == defaults.DEFAULT, ProtectedTerm.group_name == group
        )
        return (await session.execute(terms)).scalars().all()
    if store is Store.PATTERNS:
        patterns = select(CustomPattern).where(
            CustomPattern.source == defaults.DEFAULT, CustomPattern.group_name == group
        )
        return (await session.execute(patterns)).scalars().all()
    documents = select(ProtectedDocument).where(
        ProtectedDocument.source == defaults.DEFAULT, ProtectedDocument.category == group
    )
    return (await session.execute(documents)).scalars().all()


def _switch_key(row: Row) -> str:
    """What identifies a default row across pack upgrades."""
    if isinstance(row, ProtectedTerm):
        return row.term_hmac
    return row.name if isinstance(row, CustomPattern) else row.label


def _language(sample: str) -> str:
    return "el" if len(_GREEK.findall(sample)) > len(_LATIN.findall(sample)) else "en"


def _term_out(row: TermRow) -> TermOut:
    return TermOut(
        id=row.id,
        term=row.term,
        aliases=list(row.aliases),
        data_type=row.data_type,
        source=row.source,
        group=row.group,
        enabled=row.enabled,
        created=row.created,
    )


def _pattern_out(row: PatternRow) -> PatternOut:
    return PatternOut(
        id=row.id,
        name=row.name,
        regex=row.regex,
        data_type=row.data_type,
        source=row.source,
        group=row.group,
        enabled=row.enabled,
        created=row.created,
    )


def _document_out(row: DocumentRow) -> DocumentOut:
    return DocumentOut(
        id=row.id,
        label=row.label,
        category=row.category,
        language=row.language,
        source=row.source,
        chunks=row.chunks,
        embedder_id=row.embedder_id,
        stale=row.stale,
        enabled=row.enabled,
        created=row.created,
    )


def _store_summary(store: Store, rows: Sequence[tuple[RowSource, str, str, bool]]) -> StoreSummary:
    """`rows` holds (source, group, data type, enabled) for every row of the store."""
    groups: dict[tuple[RowSource, str], list[tuple[str, bool]]] = {}
    for source, group, data_type, enabled in rows:
        groups.setdefault((source, group), []).append((data_type, enabled))
    return StoreSummary(
        store=store,
        layers=[
            LayerCount(
                source=layer,
                rows=sum(source is layer for source, *_ in rows),
                enabled=sum(source is layer and enabled for source, _, _, enabled in rows),
            )
            for layer in RowSource
        ],
        groups=[
            GroupOut(
                group=group,
                source=source,
                data_type=members[0][0] if len({name for name, _ in members}) == 1 else None,
                rows=len(members),
                enabled=any(enabled for _, enabled in members),
            )
            for (source, group), members in sorted(groups.items())
        ],
    )


class ProtectedData:
    """The three stores behind detection: terms, fingerprints and custom patterns."""

    def __init__(
        self,
        deps: Deps,
        *,
        ner: NerEngine | None = None,
        term_source: TermSource | None = None,
    ) -> None:
        self._deps = deps
        self._ner = ner
        self._term_source = term_source or CrmTermSource(deps.settings.crm_url)
        self._cipher = TermCipher(deps.keys.vault)
        self._pack_version = "0"
        self._state = State()
        self._engines: dict[Scope, LocalEngine] = {}
        self._indexes: dict[Scope, FingerprintIndex] = {}
        self._vectors: dict[UUID, Matrix] = {}
        self._build_lock = asyncio.Lock()

    @property
    def pack_version(self) -> str:
        return self._pack_version

    def data_types(self) -> frozenset[str]:
        """Every type valid in a policy `data` list: built-in ones plus the company's own."""
        return self._state.data_types

    async def local_engine(self, scope: Scope = None) -> LocalEngine:
        """The T0 and T1 engine over the enabled rows, optionally of some layers only."""
        engines = self._engines
        if scope not in engines:
            async with self._build_lock:
                if scope not in engines:
                    state = self._state
                    engines[scope] = await asyncio.to_thread(
                        LocalEngine, state.pattern_rules(scope), state.term_rules(scope), self._ner
                    )
        return engines[scope]

    def fingerprint_index(self, scope: Scope = None) -> FingerprintIndex:
        """The T2 index over the enabled documents; built once per reload and scope."""
        if scope not in self._indexes:
            self._indexes[scope] = self._state.fingerprint_index(scope)
        return self._indexes[scope]

    # Loading

    async def load_default_pack(self) -> None:
        """Load `defaults/` into the stores. Safe to run on every start."""
        directory = self._deps.settings.defaults_dir
        terms, terms_version = load_term_pack(directory)
        patterns, patterns_version = load_pattern_pack(directory)
        if terms.pack_version != patterns.pack_version:
            raise ValueError("terms.yaml and patterns.yaml declare different pack versions")
        self._pack_version = terms.pack_version
        embedder = self._deps.llm.embedder_id
        async with self._deps.db.session() as session:
            # One worker at a time, so two starting together do not both insert the pack.
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _PACK_LOCK})
            await defaults.sync_terms(session, self._cipher, terms, terms_version)
            await defaults.sync_patterns(session, patterns, patterns_version)
            # A company document embedded by another model cannot be compared any more.
            await session.execute(
                update(ProtectedDocument)
                .where(ProtectedDocument.source != defaults.DEFAULT)
                .values(stale=ProtectedDocument.embedder_id != embedder)
            )
        await self.reload()
        try:
            await self._sync_exemplars(load_exemplars(directory))
        except Exception as failure:
            log.warning("category exemplars were not fingerprinted: %s", type(failure).__name__)

    async def _sync_exemplars(self, exemplars: Sequence[Exemplar]) -> None:
        """Fingerprint the category exemplars again when they or the embedder changed."""
        embedder = self._deps.llm.embedder_id
        version = content_version(
            self._pack_version,
            *(f"{item.id}\x00{item.category}\x00{item.text}".encode() for item in exemplars),
        )
        current = [row for row in self._state.documents if row.source is RowSource.DEFAULT]
        async with self._deps.db.session() as session:
            stored = await session.execute(
                select(ProtectedDocument.pack_version, ProtectedDocument.embedder_id)
                .where(ProtectedDocument.source == defaults.DEFAULT)
                .distinct()
            )
            versions = {(pack_version, embedder_id) for pack_version, embedder_id in stored}
        if versions == ({(version, embedder)} if exemplars else set()) and len(current) == len(
            exemplars
        ):
            return
        engine = await self.local_engine()
        embedded = [
            (item, await fingerprint(engine, self._deps.llm, item.text)) for item in exemplars
        ]
        async with self._deps.db.session() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _PACK_LOCK})
            switches = await defaults.Switches.load(session)
            await session.execute(
                delete(ProtectedDocument).where(ProtectedDocument.source == defaults.DEFAULT)
            )
            for item, vectors in embedded:
                category = document_category(item.category)
                await self._store_document(
                    session,
                    source=RowSource.DEFAULT,
                    label=item.id,
                    category=category,
                    language=item.language or _language(item.text[:2000]),
                    content_hash=self._cipher.content_hash(item.text),
                    vectors=vectors,
                    enabled=switches.is_on(Store.FINGERPRINTS, category, item.id),
                    pack_version=version,
                )

    async def reload(self) -> None:
        """Rebuild the in-memory matchers from the database."""
        embedder = self._deps.llm.embedder_id
        async with self._deps.db.session() as session:
            terms = self._decrypt(
                (
                    await session.execute(
                        select(ProtectedTerm).order_by(ProtectedTerm.created, ProtectedTerm.id)
                    )
                ).scalars()
            )
            patterns = tuple(
                PatternRow.read(row)
                for row in (
                    await session.execute(
                        select(CustomPattern).order_by(CustomPattern.group_name, CustomPattern.name)
                    )
                ).scalars()
            )
            documents = tuple(
                DocumentRow.read(row)
                for row in (
                    await session.execute(
                        select(ProtectedDocument).order_by(
                            ProtectedDocument.created, ProtectedDocument.label
                        )
                    )
                ).scalars()
            )
            active = {
                row.id
                for row in documents
                if row.enabled and not row.stale and row.embedder_id == embedder
            }
            await self._load_vectors(session, active - self._vectors.keys())
        self._vectors = {key: self._vectors[key] for key in active if key in self._vectors}
        state = State(
            terms=terms,
            patterns=patterns,
            documents=documents,
            vectors=dict(self._vectors),
            data_types=known_data_types(terms, patterns, documents),
        )
        engine = await asyncio.to_thread(
            LocalEngine, state.pattern_rules(None), state.term_rules(None), self._ner
        )
        self._state, self._engines, self._indexes = state, {None: engine}, {}

    def _decrypt(self, rows: Any) -> tuple[TermRow, ...]:
        terms: list[TermRow] = []
        unreadable = 0
        for row in rows:
            try:
                terms.append(TermRow.read(row, self._cipher))
            except InvalidTag:
                unreadable += 1
        if unreadable:
            log.warning("%d protected terms were written under another vault key", unreadable)
        return tuple(terms)

    async def _load_vectors(self, session: AsyncSession, missing: set[UUID]) -> None:
        """Vectors never change once stored, so only documents new to this worker are read."""
        if not missing:
            return
        chunks = await session.execute(
            select(FingerprintChunk.document_id, FingerprintChunk.vector)
            .where(FingerprintChunk.document_id.in_(missing))
            .order_by(FingerprintChunk.document_id, FingerprintChunk.chunk_index)
        )
        by_document: dict[UUID, list[list[float]]] = {}
        for document_id, vector in chunks:
            by_document.setdefault(document_id, []).append(vector)
        for document_id, vectors in by_document.items():
            self._vectors[document_id] = np.asarray(vectors, dtype=np.float32)

    async def _changed(self) -> None:
        await self._deps.bus.publish(TOPIC)

    # Reading

    def summary(self) -> ProtectedSummary:
        state = self._state
        return ProtectedSummary(
            pack_version=self._pack_version,
            embedder_id=self._deps.llm.embedder_id,
            stale_documents=sum(row.stale for row in state.documents),
            data_types=sorted(state.data_types),
            categories=sorted(DataType.CATEGORIES),
            stores=[
                _store_summary(
                    Store.TERMS,
                    [(row.source, row.group, row.data_type, row.enabled) for row in state.terms],
                ),
                _store_summary(
                    Store.FINGERPRINTS,
                    [
                        (row.source, row.category, row.category, row.enabled)
                        for row in state.documents
                    ],
                ),
                _store_summary(
                    Store.PATTERNS,
                    [(row.source, row.group, row.data_type, row.enabled) for row in state.patterns],
                ),
            ],
        )

    def list_terms(
        self,
        *,
        source: RowSource | None = None,
        group: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> TermPage:
        needle = query.casefold() if query else None
        rows = [
            row
            for row in self._state.terms
            if (source is None or row.source is source)
            and (group is None or row.group == group)
            and (
                needle is None
                or needle in row.term.casefold()
                or any(needle in alias.casefold() for alias in row.aliases)
            )
        ]
        rows.sort(key=lambda row: (row.source.value, row.group, row.term.casefold()))
        return TermPage(
            total=len(rows), items=[_term_out(row) for row in rows[offset : offset + limit]]
        )

    def list_documents(self, source: RowSource | None = None) -> list[DocumentOut]:
        return [
            _document_out(row)
            for row in self._state.documents
            if source is None or row.source is source
        ]

    def list_patterns(self, source: RowSource | None = None) -> list[PatternOut]:
        return [
            _pattern_out(row)
            for row in self._state.patterns
            if source is None or row.source is source
        ]

    def term(self, term_id: UUID) -> TermOut:
        return _term_out(self._find(self._state.terms, term_id))

    def pattern(self, pattern_id: UUID) -> PatternOut:
        return _pattern_out(self._find(self._state.patterns, pattern_id))

    def document(self, document_id: UUID) -> DocumentOut:
        return _document_out(self._find(self._state.documents, document_id))

    @staticmethod
    def _find[Row: (TermRow, PatternRow, DocumentRow)](rows: Sequence[Row], row_id: UUID) -> Row:
        for row in rows:
            if row.id == row_id:
                return row
        raise NotFoundError("There is no such row")

    # Terms

    async def import_terms(
        self, rows: Sequence[Mapping[str, Any]], source: RowSource
    ) -> ImportResult:
        """Import the valid rows and report the others, each with its row number."""
        valid, errors = validate_rows(rows)
        async with self._deps.db.session() as session:
            imported, duplicates = await self._insert_terms(session, source, valid)
        await self._changed()
        return ImportResult(imported=imported, duplicates=duplicates, errors=errors)

    async def sync_terms(self) -> ImportResult:
        """Replace the synced terms with what the term source holds now."""
        valid, errors = validate_rows(await self._term_source.fetch())
        async with self._deps.db.session() as session:
            await session.execute(
                delete(ProtectedTerm).where(ProtectedTerm.source == RowSource.SYNCED.value)
            )
            imported, duplicates = await self._insert_terms(session, RowSource.SYNCED, valid)
        await self._changed()
        return ImportResult(imported=imported, duplicates=duplicates, errors=errors)

    async def refresh_synced_terms(self) -> None:
        """At start, bring earlier-synced terms up to date. A source that is down can wait."""
        if not any(row.source is RowSource.SYNCED for row in self._state.terms):
            return
        try:
            await self.sync_terms()
        except Exception as failure:
            log.warning("terms were not synced at start: %s", type(failure).__name__)

    async def _insert_terms(
        self, session: AsyncSession, source: RowSource, terms: Sequence[NewTerm]
    ) -> tuple[int, int]:
        existing = set(
            (
                await session.execute(
                    select(ProtectedTerm.term_hmac).where(ProtectedTerm.source == source.value)
                )
            ).scalars()
        )
        rows = []
        for term in terms:
            key = self._cipher.lookup_key(term.group, term.term)
            if key in existing:
                continue
            existing.add(key)
            rows.append(
                {
                    "source": source.value,
                    "group_name": term.group,
                    "data_type": term.data_type,
                    "term": self._cipher.encrypt(term.term),
                    "aliases": self._cipher.encrypt_list(list(term.aliases)),
                    "term_hmac": key,
                    "enabled": True,
                }
            )
        if rows:
            await session.execute(insert(ProtectedTerm), rows)
        return len(rows), len(terms) - len(rows)

    # Switching and deleting, the same for all three stores

    async def set_enabled(self, store: Store, row_id: UUID, enabled: bool) -> None:
        async with self._deps.db.session() as session:
            row = await _get(session, store, row_id)
            row.enabled = enabled
            if row.source == defaults.DEFAULT:
                await defaults.set_switch(
                    session, store, _switch_key(row), is_group=False, off=not enabled
                )
        await self._changed()

    async def set_group_enabled(self, store: Store, group: str, enabled: bool) -> None:
        """Switch a whole group of the default pack. Rows switched off one by one stay off."""
        async with self._deps.db.session() as session:
            rows = await _default_group(session, store, group)
            if not rows:
                raise NotFoundError("The default pack has no such group")
            await defaults.set_switch(session, store, group, is_group=True, off=not enabled)
            switches = await defaults.Switches.load(session)
            for row in rows:
                row.enabled = enabled and not switches.row_is_off(store, _switch_key(row))
        await self._changed()

    async def delete(self, store: Store, row_id: UUID) -> None:
        async with self._deps.db.session() as session:
            row = await _get(session, store, row_id)
            if row.source == defaults.DEFAULT:
                raise ConflictError("Default rows can be switched off, but not deleted")
            await session.delete(row)
        await self._changed()

    # Documents

    async def add_document(
        self,
        *,
        filename: str,
        content: bytes,
        label: str,
        category: str,
        source: RowSource,
    ) -> DocumentUploadResult:
        """Fingerprint a document. Its text exists only in this call's memory."""
        if len(content) > MAX_DOCUMENT_BYTES:
            raise TooLargeError("A document can be at most 10 MB")
        category = document_category(category)
        document_text = await asyncio.to_thread(extract_text, filename, content)
        content_hash = self._cipher.content_hash(document_text)
        embedder = self._deps.llm.embedder_id
        async with self._deps.db.session() as session:
            existing = (
                await session.execute(
                    select(ProtectedDocument.id).where(
                        ProtectedDocument.source == source.value,
                        ProtectedDocument.content_hash == content_hash,
                        ProtectedDocument.embedder_id == embedder,
                    )
                )
            ).scalar_one_or_none()
        if existing is not None:
            return DocumentUploadResult(document=self.document(existing), duplicate=True)
        vectors = await fingerprint(await self.local_engine(), self._deps.llm, document_text)
        async with self._deps.db.session() as session:
            # The same document under an older embedder is replaced, not kept as stale.
            await session.execute(
                delete(ProtectedDocument).where(
                    ProtectedDocument.source == source.value,
                    ProtectedDocument.content_hash == content_hash,
                )
            )
            document_id = await self._store_document(
                session,
                source=source,
                label=label,
                category=category,
                language=_language(document_text[:2000]),
                content_hash=content_hash,
                vectors=vectors,
            )
        await self._changed()
        return DocumentUploadResult(document=self.document(document_id), duplicate=False)

    async def _store_document(
        self,
        session: AsyncSession,
        *,
        source: RowSource,
        label: str,
        category: str,
        language: str | None,
        content_hash: str,
        vectors: Matrix,
        enabled: bool = True,
        pack_version: str | None = None,
    ) -> UUID:
        if not len(vectors):
            raise InvalidInputError("No text could be extracted from this file")
        document = ProtectedDocument(
            source=source.value,
            label=label,
            category=category,
            language=language,
            content_hash=content_hash,
            embedder_id=self._deps.llm.embedder_id,
            chunks=len(vectors),
            stale=False,
            enabled=enabled,
            pack_version=pack_version,
        )
        session.add(document)
        await session.flush()
        await session.execute(
            insert(FingerprintChunk),
            [
                {"document_id": document.id, "chunk_index": index, "vector": vector.tolist()}
                for index, vector in enumerate(vectors)
            ],
        )
        return document.id

    # Patterns

    async def add_pattern(self, new: PatternIn, source: RowSource) -> PatternOut:
        try:
            compile_pattern(new.regex)
            data_type = span_type(new.data_type)
        except (PatternError, ValueError) as problem:
            raise InvalidInputError(str(problem)) from problem
        name = " ".join(new.name.split())
        async with self._deps.db.session() as session:
            taken = (
                await session.execute(
                    select(CustomPattern.id).where(
                        CustomPattern.source == source.value, CustomPattern.name == name
                    )
                )
            ).scalar_one_or_none()
            if taken is not None:
                raise ConflictError(f'A pattern named "{name}" already exists')
            pattern = CustomPattern(
                source=source.value,
                group_name=CUSTOM_PATTERN_GROUP,
                name=name,
                regex=new.regex,
                data_type=data_type,
                enabled=True,
            )
            session.add(pattern)
            await session.flush()
        await self._changed()
        return self.pattern(pattern.id)

    # Demo data

    async def remove_demo_data(self) -> RemoveDemoResult:
        """Clear every seeded row and the terms synced from the CRM: a default-only install."""
        seeded = RowSource.SEEDED.value
        async with self._deps.db.session() as session:
            terms = await session.execute(
                delete(ProtectedTerm)
                .where(ProtectedTerm.source.in_([seeded, RowSource.SYNCED.value]))
                .returning(ProtectedTerm.id)
            )
            documents = await session.execute(
                delete(ProtectedDocument)
                .where(ProtectedDocument.source == seeded)
                .returning(ProtectedDocument.id)
            )
            patterns = await session.execute(
                delete(CustomPattern)
                .where(CustomPattern.source == seeded)
                .returning(CustomPattern.id)
            )
            result = RemoveDemoResult(
                terms=len(terms.all()), documents=len(documents.all()), patterns=len(patterns.all())
            )
        await self._changed()
        return result
