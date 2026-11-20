from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base

SNIPPET_CHARS = 200


class Event(Base):
    """One inspected prompt, tool call or tool result. Holds no raw text and no user ID."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_team_ts", "team", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_pseudonym: Mapped[str] = mapped_column(String(64), index=True)
    team: Mapped[str] = mapped_column(String(80))
    tool: Mapped[str | None] = mapped_column(String(120), index=True)
    tool_status: Mapped[str | None] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    rule: Mapped[str] = mapped_column(String(120))
    policy_version: Mapped[int] = mapped_column(Integer)
    data_types: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    data_counts: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    tiers_ms: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    masked_snippet: Mapped[str | None] = mapped_column(String(SNIPPET_CHARS))
    conversation: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    forwarded: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String(20), default="gateway")
    agent_tool: Mapped[str | None] = mapped_column(String(120))
    tainted: Mapped[bool] = mapped_column(Boolean, default=False)
    injection: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    policy_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(200))
