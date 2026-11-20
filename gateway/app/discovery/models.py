from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base, created_at


class Tool(Base):
    """An AI tool in the inventory."""

    __tablename__ = "tools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rating_source: Mapped[str] = mapped_column(String(30))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    upstream_url: Mapped[str | None] = mapped_column(String(300))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[datetime] = created_at()


class ToolUsage(Base):
    """Requests per tool, team and day, taken from proxy and DNS logs."""

    __tablename__ = "tool_usage"

    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True
    )
    team: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    bytes_out: Mapped[int] = mapped_column(BigInteger, default=0)
    users: Mapped[int] = mapped_column(Integer, default=0)


class LogIngestion(Base):
    __tablename__ = "log_ingestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created: Mapped[datetime] = created_at()
    filename: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    lines: Mapped[int] = mapped_column(Integer)
    malformed: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer)
    new_tools: Mapped[int] = mapped_column(Integer)
