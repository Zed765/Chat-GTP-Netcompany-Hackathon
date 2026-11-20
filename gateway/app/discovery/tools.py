"""Reads inventory tools with their recent usage, and applies an analyst's changes."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.types import ToolStatus
from gateway.app.discovery.models import Tool, ToolUsage
from gateway.app.discovery.schemas import RiskFactors, TeamUsage, ToolOut, ToolUpdate

USAGE_DAYS = 14
ANALYST_CONFIRMED = "analyst_confirmed"


async def tool_views(
    session: AsyncSession,
    *,
    slug: str | None = None,
    demo_only: bool = False,
    needs_review: bool = False,
) -> list[ToolOut]:
    statement = select(Tool).order_by(func.lower(Tool.name))
    if slug is not None:
        statement = statement.where(Tool.slug == slug)
    if demo_only:
        statement = statement.where(Tool.upstream_url.is_not(None))
    if needs_review:
        statement = statement.where(Tool.needs_review)
    rows = (await session.execute(statement)).scalars().all()
    usage = await _usage_by_team(session, [row.id for row in rows])
    return [_view(row, usage[row.id]) for row in rows]


def apply_update(row: Tool, change: ToolUpdate) -> None:
    if change.status is not None:
        row.status = change.status.value
    if change.risk_score is not None:
        row.risk_score = change.risk_score
    if change.risk_factors is not None:
        row.risk_factors = change.risk_factors.model_dump()
    row.rating_source = ANALYST_CONFIRMED
    row.needs_review = False


async def _usage_by_team(
    session: AsyncSession, tool_ids: Sequence[int]
) -> dict[int, list[TeamUsage]]:
    since = datetime.now(UTC).date() - timedelta(days=USAGE_DAYS - 1)
    requests = func.sum(ToolUsage.requests)
    statement = (
        select(ToolUsage.tool_id, ToolUsage.team, requests)
        .where(ToolUsage.tool_id.in_(tool_ids), ToolUsage.day >= since)
        .group_by(ToolUsage.tool_id, ToolUsage.team)
        .order_by(requests.desc(), ToolUsage.team)
    )
    usage: defaultdict[int, list[TeamUsage]] = defaultdict(list)
    for tool_id, team, total in await session.execute(statement):
        usage[tool_id].append(TeamUsage(team=team, requests=total))
    return usage


def _view(row: Tool, usage: list[TeamUsage]) -> ToolOut:
    return ToolOut(
        slug=row.slug,
        name=row.name,
        domains=row.domains,
        category=row.category,
        description=row.description,
        status=ToolStatus(row.status),
        risk_score=row.risk_score,
        risk_factors=RiskFactors.model_validate(row.risk_factors),
        rating_source=row.rating_source,
        needs_review=row.needs_review,
        review_note=row.review_note,
        is_demo=row.upstream_url is not None,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        requests_14d=sum(team.requests for team in usage),
        usage_by_team=usage,
    )
