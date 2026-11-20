from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from gateway.app.core.deps import Deps
from gateway.app.core.types import ToolStatus
from gateway.app.discovery import InventoryService
from gateway.app.discovery.models import Tool, ToolUsage
from gateway.app.discovery.tools import tool_views

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

YESTERDAY = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=1)
TWO_DAYS_AGO = YESTERDAY - timedelta(days=1)


def _squid(when: datetime, client: str, host: str, user: str = "-", size: int = 1000) -> str:
    return (
        f"{when.timestamp():.3f}    120 {client} TCP_TUNNEL/200 {size} CONNECT {host}:443 "
        f"{user} HIER_DIRECT/203.0.113.9 -"
    )


def _dns(when: datetime, client: str, name: str) -> str:
    return f"{when.isoformat().replace('+00:00', 'Z')} {client} {name}. A"


PROXY_LOG = "\n".join(
    [
        _squid(YESTERDAY, "10.20.9.5", "chatgpt.com", "m.ioannou", 4000),
        _squid(YESTERDAY, "10.20.9.6", "files.chatgpt.com", "g.nikolaou", 500),
        _squid(YESTERDAY, "10.20.1.15", "chat.openai.com"),
        _squid(TWO_DAYS_AGO, "10.20.1.15", "chatgpt.com"),
        _squid(YESTERDAY, "10.20.4.8", "claude.ai"),
        _squid(YESTERDAY, "10.20.4.8", "app.notesly.example"),
        _squid(YESTERDAY, "10.20.4.9", "notesly.example"),
        _squid(YESTERDAY, "10.20.1.15", "www.dailyherald.example"),
        _squid(YESTERDAY, "10.20.1.15", "parcelpost.example"),
        _squid(YESTERDAY, "10.20.1.15", "undescribed-ai-chatbot.example"),
        "this line is damaged",
        f"{YESTERDAY.timestamp():.3f} 120 10.20.1.15 TCP_TUNNEL/200",
    ]
).encode()


async def _usage(deps: Deps, slug: str) -> dict[tuple[str, int], tuple[int, int, int]]:
    """Requests, bytes and people per (team, days ago) for one tool."""
    today = datetime.now(UTC).date()
    async with deps.db.session() as session:
        rows = await session.execute(
            select(ToolUsage).join(Tool, Tool.id == ToolUsage.tool_id).where(Tool.slug == slug)
        )
        return {
            (row.team, (today - row.day).days): (row.requests, row.bytes_out, row.users)
            for row in rows.scalars()
        }


async def test_proxy_log_updates_usage_per_team_and_day(
    inventory: InventoryService, deps: Deps
) -> None:
    result = await inventory.ingest(PROXY_LOG, "access.log", "squid")

    assert (result.lines, result.malformed, result.duplicate) == (12, 2, False)
    # Seven lines belong to tools: four to ChatGPT, one to Claude, two to the new tool.
    assert (result.matched, result.new_tools) == (7, 1)
    assert result.new_tool_slugs == ["notesly-example"]
    assert await _usage(deps, "chatgpt") == {
        ("Legal", 1): (2, 4500, 2),
        ("Sales", 1): (1, 1000, 1),
        ("Sales", 2): (1, 1000, 1),
    }
    assert await _usage(deps, "claude") == {("Engineering", 1): (1, 1000, 1)}
    async with deps.db.session() as session:
        [chatgpt] = await tool_views(session, slug="chatgpt")
        [gemini] = await tool_views(session, slug="gemini")
    assert (chatgpt.first_seen, chatgpt.last_seen) == (TWO_DAYS_AGO, YESTERDAY)
    assert chatgpt.requests_14d == 4
    assert [(team.team, team.requests) for team in chatgpt.usage_by_team] == [
        ("Legal", 2),
        ("Sales", 2),
    ]
    assert (gemini.first_seen, gemini.requests_14d, gemini.usage_by_team) == (None, 0, [])


async def test_unknown_ai_domain_reaches_the_review_queue_and_other_sites_do_not(
    inventory: InventoryService, deps: Deps
) -> None:
    await inventory.ingest(PROXY_LOG, "access.log", "squid")

    async with deps.db.session() as session:
        queue = await tool_views(session, needs_review=True)
        domains = {
            domain
            for row in (await session.execute(select(Tool))).scalars()
            for domain in row.domains
        }
    [notesly] = queue
    assert (notesly.slug, notesly.name, notesly.domains) == (
        "notesly-example",
        "Notesly AI",
        ["notesly.example"],
    )
    assert (notesly.status, notesly.rating_source, notesly.category) == (
        ToolStatus.UNKNOWN,
        "model_drafted",
        "meeting assistant",
    )
    # Nothing in the description answers the four risk questions, so the draft is cautious.
    assert notesly.risk_score == 5
    assert notesly.risk_factors.sso is True and notesly.risk_factors.certifications == ["SOC 2"]
    assert notesly.review_note == (
        "Drafted by the model from the site's description. "
        "The description calls it an AI meeting assistant."
    )
    assert notesly.requests_14d == 2
    # A news site, a parcel tracker and a site nobody described are not AI tools.
    assert not {"dailyherald.example", "parcelpost.example"} & domains
    assert not any("undescribed" in domain for domain in domains)

    # The next request to it resolves to the new entry, subdomains included.
    resolved = await inventory.resolve("eu.notesly.example")
    assert (resolved.slug, resolved.status) == ("notesly-example", ToolStatus.UNKNOWN)


async def test_the_same_file_is_ingested_once(inventory: InventoryService, deps: Deps) -> None:
    first = await inventory.ingest(PROXY_LOG, "access.log", "squid")
    usage = await _usage(deps, "chatgpt")

    again = await inventory.ingest(PROXY_LOG, "renamed.log", "squid")

    assert again.duplicate and again.id == first.id
    assert (again.filename, again.new_tool_slugs) == ("access.log", [])
    assert await _usage(deps, "chatgpt") == usage
    async with deps.db.session() as session:
        count = await session.execute(text("SELECT count(*) FROM log_ingestions"))
        assert count.scalar_one() == 1


async def test_a_second_file_adds_to_the_same_days(inventory: InventoryService, deps: Deps) -> None:
    await inventory.ingest(PROXY_LOG, "access.log", "squid")
    more = "\n".join(
        [
            _squid(YESTERDAY, "10.20.9.5", "chatgpt.com", "m.ioannou", 100),
            _squid(YESTERDAY, "10.20.4.8", "notesly.example"),
        ]
    ).encode()

    result = await inventory.ingest(more, "access-2.log", "squid")

    assert (result.matched, result.new_tools, result.duplicate) == (2, 0, False)
    usage = await _usage(deps, "chatgpt")
    # People are counted per file, so the larger count stands rather than the sum.
    assert usage["Legal", 1] == (3, 4600, 2)
    assert (await _usage(deps, "notesly-example"))["Engineering", 1][0] == 3


async def test_dns_log(inventory: InventoryService, deps: Deps) -> None:
    log = "\n".join(
        [
            _dns(YESTERDAY, "10.20.1.15", "chat.mistral.ai"),
            _dns(YESTERDAY, "10.20.1.16", "chat.mistral.ai"),
            _dns(YESTERDAY, "10.20.4.8", "promptforge.example"),
            _dns(YESTERDAY, "10.20.4.8", "printer.internal"),
            "2026-11-10 broken",
        ]
    ).encode()

    result = await inventory.ingest(log, "queries.dns", "dns")

    assert (result.kind, result.lines, result.malformed) == ("dns", 5, 1)
    assert (result.matched, result.new_tool_slugs) == (3, ["promptforge-example"])
    assert await _usage(deps, "mistral-le-chat") == {("Sales", 1): (2, 0, 2)}


async def test_ingestion_keeps_no_identities(inventory: InventoryService, deps: Deps) -> None:
    await inventory.ingest(PROXY_LOG, "access.log", "squid")

    async with deps.db.session() as session:
        stored = await session.execute(
            text(
                "SELECT row_to_json(t)::text FROM tool_usage t UNION ALL "
                "SELECT row_to_json(l)::text FROM log_ingestions l"
            )
        )
        everything = "\n".join(row[0] for row in stored)
    # The log named two people and several client addresses; none of them is kept.
    for identity in ("m.ioannou", "g.nikolaou", "10.20.9.5", "10.20.1.15", "10.20.4.8"):
        assert identity not in everything
