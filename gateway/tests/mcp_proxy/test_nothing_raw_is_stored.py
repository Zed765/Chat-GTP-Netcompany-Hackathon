"""Scene 3 with the real event writer and database: what is left behind afterwards."""

import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from gateway.app.core.keys import Keys
from gateway.app.db.session import Database
from gateway.app.events.writer import EventWriter
from gateway.tests.mcp_proxy.fakes import EMPLOYEE, make_stack
from gateway.tests.mcp_proxy.inprocess import running_gateway
from gateway.tests.mcp_proxy.test_proxy_roundtrip import POISONED_URL, fixture_values, text_of


@pytest.mark.integration
async def test_events_and_redis_hold_no_raw_value_and_no_flagged_text(
    db: Database, keys: Keys, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = make_stack(redis, events=EventWriter(db, keys.pseudonym))
    async with running_gateway(stack.services, monkeypatch) as gateway:
        session_id = await gateway.new_session()
        async with gateway.tools(session_id) as client:
            await client.call_tool("web.fetch_page", {"url": POISONED_URL})
            listing = await client.call_tool("crm.search_clients", {"query": ""})
            body = {"to": "<EMAIL_1>", "subject": "Client export", "body": text_of(listing)}
            await client.call_tool("mail.send_email", body)

    async with db.session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT channel, action, agent_tool, tainted, user_pseudonym, injection, "
                    "row_to_json(events)::text AS everything FROM events "
                    "WHERE conversation = :id ORDER BY id"
                ),
                {"id": session_id},
            )
        ).all()
    assert [(row.channel, row.action, row.agent_tool) for row in rows] == [
        ("tool_call", "redact", "web.fetch_page"),
        ("tool_result", "redact", "web.fetch_page"),
        ("tool_call", "allow", "crm.search_clients"),
        ("tool_result", "redact", "crm.search_clients"),
        ("tool_call", "block", "mail.send_email"),
    ]
    flagged = rows[1].injection
    assert flagged["flagged"] and "evidence" not in flagged
    assert flagged["layers_run"] == ["heuristics", "model"]
    assert rows[-1].tainted and EMPLOYEE.user_id not in rows[0].user_pseudonym

    keys_in_redis = [key async for key in redis.scan_iter("*")]
    sessions = [str(await redis.hgetall(key)) for key in keys_in_redis if ":session:" in key]
    stored = " ".join([row.everything for row in rows] + keys_in_redis + sessions)
    assert sessions and "ignore your previous" not in stored and "supplier-portal" not in stored
    assert [value for value in fixture_values() if value in stored] == []
