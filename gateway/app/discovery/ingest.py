"""Ingests one log file: usage per tool, team and day, and new AI tools for the review queue."""

import asyncio
import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.deps import Deps
from gateway.app.core.types import ToolStatus
from gateway.app.discovery.classify import (
    SiteDescription,
    ToolDraft,
    draft_tools,
    read_site_descriptions,
    risk_score,
)
from gateway.app.discovery.index import ToolIndex, with_parents
from gateway.app.discovery.logs import HostUsage, LogSummary, summarise
from gateway.app.discovery.models import LogIngestion, Tool, ToolUsage
from gateway.app.discovery.schemas import IngestionResult, LogKind

MODEL_DRAFTED = "model_drafted"
_INGEST_LOCK = 741_004
_USAGE_BATCH = 1000


async def ingest_log(
    deps: Deps, index: ToolIndex, content: bytes, filename: str, kind: LogKind
) -> IngestionResult:
    """Ingest a file once; the same content again is reported as a duplicate."""
    digest = hashlib.sha256(content).hexdigest()
    async with deps.db.session() as session:
        earlier = await _by_hash(session, digest)
    if earlier is not None:
        return _result(earlier, duplicate=True)
    summary = await asyncio.to_thread(summarise, content, kind, deps.directory.team_of)
    sites = await asyncio.to_thread(
        _described_unknown_hosts, deps.settings.site_descriptions_path, index, summary
    )
    drafts = await draft_tools(deps.llm, sites)
    async with deps.db.session() as session:
        # One ingestion at a time, so two files cannot add the same tool or count twice.
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INGEST_LOCK})
        earlier = await _by_hash(session, digest)
        if earlier is not None:
            return _result(earlier, duplicate=True)
        tools = list((await session.execute(select(Tool))).scalars())
        added = _new_tools(drafts, tools)
        session.add_all(added)
        await session.flush()
        tools += added
        usage = _usage_per_tool(summary, ToolIndex.of(tools))
        await _record_usage(session, usage, {tool.slug: tool.id for tool in tools})
        record = LogIngestion(
            filename=filename[:200],
            kind=kind,
            content_hash=digest,
            lines=summary.lines,
            malformed=summary.malformed,
            matched=sum(traffic.requests for traffic in usage.values()),
            new_tools=len(added),
        )
        session.add(record)
    if added:
        await deps.bus.publish("inventory")
    return _result(record, duplicate=False, new_tool_slugs=[tool.slug for tool in added])


async def _by_hash(session: AsyncSession, digest: str) -> LogIngestion | None:
    statement = select(LogIngestion).where(LogIngestion.content_hash == digest)
    return (await session.execute(statement)).scalar_one_or_none()


def _result(
    record: LogIngestion, *, duplicate: bool, new_tool_slugs: Sequence[str] = ()
) -> IngestionResult:
    return IngestionResult(
        id=record.id,
        created=record.created,
        filename=record.filename,
        kind=record.kind,
        lines=record.lines,
        malformed=record.malformed,
        matched=record.matched,
        new_tools=record.new_tools,
        duplicate=duplicate,
        new_tool_slugs=list(new_tool_slugs),
    )


def _described_unknown_hosts(
    descriptions: Path, index: ToolIndex, summary: LogSummary
) -> dict[str, SiteDescription]:
    """Site descriptions for the hosts no tool claims. A host without one is ignored."""
    sites = read_site_descriptions(descriptions)
    described: dict[str, SiteDescription] = {}
    for host in summary.hosts:
        if index.find_host(host) is None:
            domain = next((name for name in with_parents(host) if name in sites), None)
            if domain is not None:
                described[domain] = sites[domain]
    return described


def _new_tools(drafts: Sequence[ToolDraft], existing: Sequence[Tool]) -> list[Tool]:
    index = ToolIndex.of(existing)
    slugs = {tool.slug for tool in existing}
    added: list[Tool] = []
    for draft in drafts:
        if index.find_host(draft.domain) is not None:
            continue
        slug = base = re.sub(r"[^a-z0-9]+", "-", draft.domain).strip("-")[:100]
        suffix = 2
        while slug in slugs:
            slug, suffix = f"{base}-{suffix}", suffix + 1
        slugs.add(slug)
        added.append(
            Tool(
                slug=slug,
                name=draft.name,
                domains=[draft.domain],
                category=draft.category,
                description=draft.description,
                status=ToolStatus.UNKNOWN.value,
                risk_score=risk_score(draft.risk_factors),
                risk_factors=draft.risk_factors.model_dump(),
                rating_source=MODEL_DRAFTED,
                needs_review=True,
                review_note=draft.note,
            )
        )
    return added


def _usage_per_tool(summary: LogSummary, index: ToolIndex) -> dict[str, HostUsage]:
    per_tool: dict[str, HostUsage] = {}
    for host, usage in summary.hosts.items():
        tool = index.find_host(host)
        if tool is not None:
            total = per_tool.setdefault(tool.slug, HostUsage(usage.first_seen, usage.last_seen))
            total.add(usage)
    return per_tool


async def _record_usage(
    session: AsyncSession, usage: Mapping[str, HostUsage], ids: Mapping[str, int]
) -> None:
    rows = [
        {
            "tool_id": ids[slug],
            "team": team[:80],
            "day": day,
            "requests": cell.requests,
            "bytes_out": cell.bytes_out,
            "users": len(cell.people),
        }
        for slug, traffic in usage.items()
        for (team, day), cell in traffic.cells.items()
    ]
    for start in range(0, len(rows), _USAGE_BATCH):
        statement = insert(ToolUsage).values(rows[start : start + _USAGE_BATCH])
        new = statement.excluded
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[ToolUsage.tool_id, ToolUsage.team, ToolUsage.day],
                set_={
                    "requests": ToolUsage.requests + new.requests,
                    "bytes_out": ToolUsage.bytes_out + new.bytes_out,
                    # People are counted per file and never stored, so files cannot be
                    # merged exactly; the largest count seen is a safe lower bound.
                    "users": func.greatest(ToolUsage.users, new.users),
                },
            )
        )
    for slug, traffic in usage.items():
        await session.execute(
            update(Tool)
            .where(Tool.id == ids[slug])
            .values(
                first_seen=func.least(Tool.first_seen, traffic.first_seen),
                last_seen=func.greatest(Tool.last_seen, traffic.last_seen),
            )
        )
