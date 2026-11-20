import hashlib
import hmac
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import CursorResult, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.types import (
    Action,
    Channel,
    InjectionVerdict,
    PolicyContext,
    Tier,
    ToolStatus,
    Usage,
)
from gateway.app.db.session import Database
from gateway.app.events.models import SNIPPET_CHARS, Event

ORIGIN_GATEWAY = "gateway"
ORIGIN_IMPORT = "import"
ORIGIN_LOG = "log"


def pseudonym(user_id: str, key: bytes) -> str:
    return hmac.new(key, user_id.encode(), hashlib.sha256).hexdigest()


def _storable(value: Any) -> Any:
    """`value` as Postgres can hold it: no NUL character in any string, key or JSON value."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_storable(key): _storable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_storable(item) for item in value]
    return value


class EventWriteError(RuntimeError):
    """An event could not be stored. The message names the kind of failure and nothing else."""


class EventRecord(BaseModel):
    """What the pipeline reports about one inspection. It has no field for raw text."""

    user_id: str
    team: str
    channel: Channel
    action: Action
    rule: str
    policy_version: int
    tool: str | None = None
    tool_status: ToolStatus | None = None
    data_counts: dict[str, int] = Field(default_factory=dict)
    timings_ms: dict[Tier, float] = Field(default_factory=dict)
    latency_ms: float = 0.0
    usage: Usage = Usage()
    masked_snippet: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None
    forwarded: bool = True
    origin: str = Field(
        default=ORIGIN_GATEWAY,
        description=(
            "`gateway`: inspected in the path. `import`: imported history, recorded as if the "
            "policy had applied. `log`: seen in a log, so it reached the tool as written"
        ),
    )
    agent_tool: str | None = None
    tainted: bool = False
    injection: InjectionVerdict | None = None
    policy_context: PolicyContext | None = Field(
        default=None, description="Kept so a draft policy can be replayed against this event"
    )
    error: str | None = None
    ts: datetime | None = None


class EventWriter:
    def __init__(self, db: Database, pseudonym_key: bytes) -> None:
        self._db = db
        self._key = pseudonym_key
        self.store_snippets = True

    def pseudonym(self, user_id: str) -> str:
        return pseudonym(user_id, self._key)

    def _row(self, record: EventRecord) -> Event:
        snippet = record.masked_snippet if self.store_snippets else None
        verdict = record.injection
        context = record.policy_context
        fields = {
            "ts": record.ts or datetime.now(UTC),
            "user_pseudonym": self.pseudonym(record.user_id),
            "team": record.team,
            "tool": record.tool,
            "tool_status": record.tool_status,
            "channel": record.channel,
            "action": record.action,
            "rule": record.rule,
            "policy_version": record.policy_version,
            "data_types": sorted(record.data_counts),
            "data_counts": record.data_counts,
            "tiers_ms": {tier.value: round(ms, 2) for tier, ms in record.timings_ms.items()},
            "latency_ms": round(record.latency_ms, 2),
            "tokens_in": record.usage.input_tokens,
            "tokens_out": record.usage.output_tokens,
            "cost_usd": record.usage.cost_usd,
            "masked_snippet": snippet[:SNIPPET_CHARS] if snippet else None,
            "conversation": record.conversation_id,
            "trace_id": record.trace_id,
            "forwarded": record.forwarded,
            "origin": record.origin,
            "agent_tool": record.agent_tool,
            "tainted": record.tainted,
            # The evidence span is raw text from an untrusted source, so it is left out.
            "injection": verdict.model_dump(exclude={"evidence"}) if verdict else None,
            "policy_context": context.model_dump(mode="json") if context else None,
            "error": record.error[:200] if record.error else None,
        }
        return Event(**_storable(fields))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A transaction to write events in. If it fails, the error names the kind of failure
        and nothing else: a database error quotes its statement and can quote the values it
        was given, and whoever logs the failure must not get either."""
        try:
            async with self._db.session() as session:
                yield session
        except SQLAlchemyError as failure:
            kind = type(failure).__name__
            raise EventWriteError(f"An event could not be stored ({kind})") from None

    async def write(self, record: EventRecord) -> int:
        event = self._row(record)
        async with self.transaction() as session:
            session.add(event)
            await session.flush()
            return event.id

    async def write_many(self, records: Sequence[EventRecord]) -> None:
        async with self.transaction() as session:
            session.add_all(self._row(record) for record in records)

    async def mark_forwarded(self, trace_id: str, user_id: str) -> bool:
        """Record that the user acknowledged a warning and the masked prompt was sent."""
        async with self.transaction() as session:
            result = await session.execute(
                update(Event)
                .where(Event.trace_id == trace_id, Event.user_pseudonym == self.pseudonym(user_id))
                .values(forwarded=True)
            )
            return bool(cast(CursorResult[Any], result).rowcount)
