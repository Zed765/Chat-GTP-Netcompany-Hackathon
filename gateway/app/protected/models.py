from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, REAL
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base, created_at


class ProtectedTerm(Base):
    """A term for the T1 matcher. `term` and `aliases` are AES-GCM ciphertext."""

    __tablename__ = "protected_terms"
    __table_args__ = (UniqueConstraint("source", "term_hmac"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(20), index=True)
    group_name: Mapped[str] = mapped_column(String(80), index=True)
    data_type: Mapped[str] = mapped_column(String(60))
    term: Mapped[bytes] = mapped_column(LargeBinary)
    aliases: Mapped[bytes | None] = mapped_column(LargeBinary)
    term_hmac: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pack_version: Mapped[str | None] = mapped_column(String(40))
    created: Mapped[datetime] = created_at()


class CustomPattern(Base):
    """A regex-only T0 recogniser, compiled with RE2."""

    __tablename__ = "custom_patterns"
    __table_args__ = (UniqueConstraint("source", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(20), index=True)
    group_name: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    regex: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pack_version: Mapped[str | None] = mapped_column(String(40))
    created: Mapped[datetime] = created_at()


class ProtectedDocument(Base):
    """A fingerprinted document. Only its label, hash and vectors are kept, never its text."""

    __tablename__ = "protected_documents"
    __table_args__ = (UniqueConstraint("source", "content_hash", "embedder_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    language: Mapped[str | None] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedder_id: Mapped[str] = mapped_column(String(120))
    chunks: Mapped[int] = mapped_column(Integer)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pack_version: Mapped[str | None] = mapped_column(String(40))
    created: Mapped[datetime] = created_at()


class FingerprintChunk(Base):
    __tablename__ = "fingerprint_chunks"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("protected_documents.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    vector: Mapped[list[float]] = mapped_column(ARRAY(REAL))


class DefaultSwitch(Base):
    """A default row or group that is switched off. Kept apart so it survives a pack upgrade."""

    __tablename__ = "default_switches"

    store: Mapped[str] = mapped_column(String(20), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    is_group: Mapped[bool] = mapped_column(Boolean, primary_key=True)
