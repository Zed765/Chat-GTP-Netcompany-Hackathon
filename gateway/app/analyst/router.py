from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import column, select, table
from sqlalchemy.sql import ColumnElement

from gateway.app.analyst.ask import NoAnswerError, answer
from gateway.app.analyst.events import list_events
from gateway.app.analyst.overview import build_overview
from gateway.app.analyst.questions import EXAMPLES
from gateway.app.analyst.schemas import (
    AskRequest,
    AskResult,
    EventOut,
    EventPage,
    Overview,
    Suggestion,
)
from gateway.app.core.auth import Admin
from gateway.app.core.services import Svc
from gateway.app.core.types import Action, Channel
from gateway.app.events.models import Event

router = APIRouter(prefix="/api", tags=["analyst"])


@router.get("/overview")
async def overview(_: Admin, services: Svc, days: int = Query(default=14, ge=1, le=90)) -> Overview:
    return await build_overview(services.db, days)


@router.get("/events")
async def events(
    _: Admin,
    services: Svc,
    team: str | None = None,
    tool: str | None = None,
    action: Action | None = None,
    channel: Channel | None = None,
    data_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> EventPage:
    """Events at team level, newest first. They carry no user identity."""
    filters: list[ColumnElement[bool]] = []
    if team:
        # The shown team, so a small team folded into "Other" cannot be picked out by name.
        folded = table("v_events", column("id"), column("team"))
        filters.append(Event.id.in_(select(folded.c.id).where(folded.c.team == team)))
    if tool:
        filters.append(Event.tool == tool)
    if action:
        filters.append(Event.action == action.value)
    if channel:
        filters.append(Event.channel == channel.value)
    if data_type:
        filters.append(Event.data_types.contains([data_type]))
    return await list_events(services.db, filters=filters, offset=offset, limit=limit)


@router.get("/events/{event_id}")
async def event(event_id: int, _: Admin, services: Svc) -> EventOut:
    """One event, with what was found in it and what was done."""
    page = await list_events(services.db, filters=[Event.id == event_id], offset=0, limit=1)
    if not page.items:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such event")
    return page.items[0]


@router.get("/ask/suggestions")
async def suggestions(_: Admin) -> list[Suggestion]:
    return [Suggestion(question=example.question) for example in EXAMPLES]


@router.post("/ask")
async def ask(body: AskRequest, _: Admin, services: Svc) -> AskResult:
    """Answer a question in plain language with a table, the SQL behind it and a sentence."""
    try:
        return await answer(services.readonly_db, services.llm, body.question)
    except NoAnswerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
