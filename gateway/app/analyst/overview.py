"""The Overview dashboard, computed from the team-level view `v_events`."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.analyst.schemas import (
    ActionCount,
    Heatmap,
    Overview,
    ToolCount,
    TrendPoint,
    TypeCount,
)
from gateway.app.core.types import Action
from gateway.app.db.session import Database

TOP_TYPES = 8
TOP_TOOLS = 5

_WINDOW = "channel = 'prompt' AND ts >= :since"

_TOTALS = text(f"""
    SELECT count(*) AS total, count(*) FILTER (WHERE sensitive) AS sensitive
    FROM v_events WHERE {_WINDOW}
""")  # noqa: S608
_ACTIONS = text(f"SELECT action, count(*) AS n FROM v_events WHERE {_WINDOW} GROUP BY action")  # noqa: S608
_TYPES = text(f"""
    SELECT data_type, count(*) AS n
    FROM v_events, unnest(data_types) AS data_type
    WHERE {_WINDOW}
    GROUP BY data_type ORDER BY n DESC, data_type LIMIT :top
""")  # noqa: S608
_TOOLS = text(f"""
    SELECT tool, coalesce(tool_name, tool) AS name, tool_status, count(*) AS n
    FROM v_events
    WHERE {_WINDOW} AND tool_status IN ('unapproved', 'unknown') AND tool IS NOT NULL
    GROUP BY tool, tool_name, tool_status ORDER BY n DESC, tool LIMIT :top
""")  # noqa: S608
_HEATMAP = text(f"""
    SELECT team, data_type, count(*) AS n
    FROM v_events, unnest(data_types) AS data_type
    WHERE {_WINDOW}
    GROUP BY team, data_type
""")  # noqa: S608
_TREND = text(f"""
    SELECT day,
           count(*) AS total,
           count(*) FILTER (WHERE sensitive) AS sensitive,
           count(*) FILTER (WHERE action = 'allow') AS allow,
           count(*) FILTER (WHERE action = 'redact') AS redact,
           count(*) FILTER (WHERE action = 'warn') AS warn,
           count(*) FILTER (WHERE action = 'block') AS block
    FROM v_events WHERE {_WINDOW}
    GROUP BY day
""")  # noqa: S608


async def _rows(session: AsyncSession, query: Any, **params: Any) -> list[Any]:
    return list((await session.execute(query, params)).all())


def _trend(rows: list[Any], first_day: date, days: int) -> list[TrendPoint]:
    """One point per day, including days with no events."""
    by_day = {row.day: row for row in rows}
    points = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        row = by_day.get(day)
        counts = {
            name: getattr(row, name) if row else 0
            for name in ("total", "sensitive", "allow", "redact", "warn", "block")
        }
        points.append(TrendPoint(day=day, **counts))
    return points


def _heatmap(rows: list[Any], data_types: list[str]) -> Heatmap:
    teams = sorted({row.team for row in rows})
    counts = {(row.team, row.data_type): row.n for row in rows}
    return Heatmap(
        teams=teams,
        data_types=data_types,
        cells=[[counts.get((team, data_type), 0) for data_type in data_types] for team in teams],
    )


async def build_overview(db: Database, days: int) -> Overview:
    now = datetime.now(UTC)
    first_day = now.date() - timedelta(days=days - 1)
    since = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    async with db.session() as session:
        totals = (await session.execute(_TOTALS, {"since": since})).one()
        actions = {row.action: row.n for row in await _rows(session, _ACTIONS, since=since)}
        types = await _rows(session, _TYPES, since=since, top=TOP_TYPES)
        tools = await _rows(session, _TOOLS, since=since, top=TOP_TOOLS)
        heat = await _rows(session, _HEATMAP, since=since)
        trend = await _rows(session, _TREND, since=since)
    return Overview(
        days=days,
        generated=now,
        prompts_inspected=totals.total,
        sensitive_share=totals.sensitive / totals.total if totals.total else 0.0,
        actions=[
            ActionCount(action=action, count=actions.get(action.value, 0)) for action in Action
        ],
        top_data_types=[TypeCount(data_type=row.data_type, count=row.n) for row in types],
        top_unapproved_tools=[
            ToolCount(tool=row.tool, name=row.name, status=row.tool_status, count=row.n)
            for row in tools
        ],
        heatmap=_heatmap(heat, [row.data_type for row in types]),
        trend=_trend(trend, first_day, days),
    )
