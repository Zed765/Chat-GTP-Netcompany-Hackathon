"""Events as analysts browse them: team level, with no user identity."""

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.sql import ColumnElement

from gateway.app.analyst.schemas import EventOut, EventPage
from gateway.app.core.types import Action, Channel
from gateway.app.db.session import Database
from gateway.app.events.models import Event
from gateway.app.events.writer import ORIGIN_LOG

# The view decides which team name may be shown (small teams become "Other").
_SHOWN_TEAM = text("SELECT id, team FROM v_events WHERE id = ANY(:ids)")


def event_out(event: Event, team: str) -> EventOut:
    return EventOut(
        id=event.id,
        ts=event.ts,
        team=team,
        tool=event.tool,
        tool_status=event.tool_status,
        channel=Channel(event.channel),
        action=Action(event.action),
        rule=event.rule,
        policy_version=event.policy_version,
        data_counts=event.data_counts,
        masked_snippet=event.masked_snippet,
        forwarded=event.forwarded,
        sent_unmasked=event.forwarded and (event.origin == ORIGIN_LOG or event.action == "allow"),
        origin=event.origin,
        agent_tool=event.agent_tool,
        tainted=event.tainted,
        injection_flagged=bool(event.injection and event.injection.get("flagged")),
    )


async def list_events(
    db: Database,
    *,
    filters: list[ColumnElement[bool]],
    offset: int,
    limit: int,
    own_team: str | None = None,
) -> EventPage:
    """A page of events, newest first. `own_team` shows a user their own events under their
    real team name instead of the folded one."""
    query = select(Event).where(*filters)
    async with db.session() as session:
        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        events = (
            (await session.execute(query.order_by(Event.ts.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        shown: dict[Any, str] = {}
        if own_team is None and events:
            rows = await session.execute(_SHOWN_TEAM, {"ids": [event.id for event in events]})
            shown = {row.id: row.team for row in rows}
    items = [event_out(event, own_team or shown.get(event.id, event.team)) for event in events]
    return EventPage(total=total, items=items)
