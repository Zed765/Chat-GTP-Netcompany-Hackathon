from redis.asyncio import Redis

from gateway.app.mcp_proxy.sessions import (
    CANARY_PREFIX,
    AgentSessions,
    call_fingerprint,
)


async def test_each_session_gets_its_own_random_canary(redis: Redis) -> None:
    sessions = AgentSessions(redis, ttl_seconds=60)
    first, second = await sessions.create("v.tsioutsias"), await sessions.create("v.tsioutsias")
    assert first.session_id != second.session_id and first.canary != second.canary
    assert first.canary.startswith(CANARY_PREFIX) and len(first.canary) == len(CANARY_PREFIX) + 16
    assert await sessions.get(first.session_id) == first
    assert 0 < await redis.ttl(f"aspida:agent:session:{first.session_id}") <= 60


async def test_taint_records_where_it_first_came_from(redis: Redis) -> None:
    sessions = AgentSessions(redis, ttl_seconds=60)
    state = await sessions.create("v.tsioutsias")
    assert not state.tainted and state.taint_source is None

    await sessions.taint(state.session_id, "web.fetch_page")
    await sessions.taint(state.session_id, "mail.read_email")
    tainted = await sessions.get(state.session_id)
    assert tainted and tainted.tainted and tainted.taint_source == "web.fetch_page"


async def test_held_call_is_released_once_and_only_for_the_same_call(redis: Redis) -> None:
    sessions = AgentSessions(redis, ttl_seconds=60)
    session_id = (await sessions.create("v.tsioutsias")).session_id
    held = call_fingerprint("mail.send_email", {"to": "a@b.example", "body": "x"})
    same = call_fingerprint("mail.send_email", {"body": "x", "to": "a@b.example"})
    other = call_fingerprint("mail.send_email", {"to": "a@b.example", "body": "y"})
    assert held == same != other

    await sessions.hold(session_id, "call-1", held)
    assert not await sessions.release(session_id, "call-2", held)
    assert await sessions.release(session_id, "call-1", same)
    assert not await sessions.release(session_id, "call-1", same)

    await sessions.hold(session_id, "call-3", held)
    assert not await sessions.release(session_id, "call-3", other)


async def test_ending_a_session_forgets_it_and_its_held_calls(redis: Redis) -> None:
    sessions = AgentSessions(redis, ttl_seconds=60)
    kept, ended = await sessions.create("v.tsioutsias"), await sessions.create("v.tsioutsias")
    await sessions.hold(ended.session_id, "call-1", "f" * 64)
    await sessions.end(ended.session_id)

    assert await sessions.get(ended.session_id) is None
    assert await sessions.get(kept.session_id) == kept
    assert [key async for key in redis.scan_iter("aspida:agent:held:*")] == []
