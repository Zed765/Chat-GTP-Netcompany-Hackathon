from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action, Channel
from gateway.app.events.writer import EventRecord
from gateway.tests.conftest import Api

EMPLOYEE, ADMIN = DEMO_USERS
pytestmark = pytest.mark.integration


async def _event(api: Api, *, days_ago: int = 0) -> int:
    return await api.services.events.write(
        EventRecord(
            ts=datetime.now(UTC) - timedelta(days=days_ago),
            user_id=EMPLOYEE.user_id,
            team=EMPLOYEE.team,
            channel=Channel.PROMPT,
            action=Action.REDACT,
            rule="pii-and-client-data",
            policy_version=1,
            data_counts={"AFM": 1},
            conversation_id="conv-1",
        )
    )


async def test_only_an_admin_looks_up_who_sent_an_event(api: Api) -> None:
    event_id = await _event(api)
    admin = api.as_(ADMIN)
    identity = f"/api/events/{event_id}/identity"

    assert (await api.client.get(identity, headers=api.as_(EMPLOYEE))).status_code == 403
    revealed = (await api.client.get(identity, headers=admin)).json()
    assert revealed["user_id"] == EMPLOYEE.user_id and revealed["team"] == "Sales"
    assert (await api.client.get("/api/events/0/identity", headers=admin)).status_code == 404


async def test_retention_change_purges_old_events_and_only_an_admin_may_change_it(api: Api) -> None:
    old = await _event(api, days_ago=40)
    recent = await _event(api, days_ago=2)
    refused = await api.client.put(
        "/api/privacy/settings", json={"retention_days": 30}, headers=api.as_(EMPLOYEE)
    )
    assert refused.status_code == 403
    changed = await api.client.put(
        "/api/privacy/settings", json={"retention_days": 30}, headers=api.as_(ADMIN)
    )
    assert changed.json()["retention_days"] == 30
    async with api.services.db.session() as session:
        left = set((await session.execute(text("SELECT id FROM events"))).scalars())
    assert old not in left and recent in left
    await api.client.put(
        "/api/privacy/settings", json={"retention_days": 90}, headers=api.as_(ADMIN)
    )


async def test_snippets_can_be_switched_off(api: Api) -> None:
    dpo = api.as_(ADMIN)
    off = {"retention_days": 90, "store_snippets": False}
    assert (await api.client.put("/api/privacy/settings", json=off, headers=dpo)).status_code == 200
    record = EventRecord(
        user_id=EMPLOYEE.user_id,
        team=EMPLOYEE.team,
        channel=Channel.PROMPT,
        action=Action.REDACT,
        rule="pii-and-client-data",
        policy_version=1,
        masked_snippet="Reply to <PERSON_1>",
    )
    event_id = await api.services.events.write(record)
    async with api.services.db.session() as session:
        snippet = await session.scalar(
            text("SELECT masked_snippet FROM events WHERE id = :id"), {"id": event_id}
        )
    assert snippet is None
    await api.client.put("/api/privacy/settings", json={"retention_days": 90}, headers=dpo)
    assert api.services.events.store_snippets is True


async def test_my_data_shows_a_user_their_own_events_only(api: Api) -> None:
    await _event(api)
    mine = (await api.client.get("/api/privacy/my-data", headers=api.as_(EMPLOYEE))).json()
    assert mine["user_id"] == EMPLOYEE.user_id and mine["event_count"] >= 1
    assert all(event["team"] == "Sales" for event in mine["events"])
    theirs = (await api.client.get("/api/privacy/my-data", headers=api.as_(ADMIN))).json()
    assert theirs["event_count"] == 0


async def test_directory_import_resolves_users_and_addresses_to_teams(api: Api) -> None:
    body = {
        "users": [{"user_id": "g.nikolaou", "display_name": "Giorgos Nikolaou", "team": "Legal"}],
        "networks": [{"cidr": "10.20.3.0/24", "team": "Finance"}],
    }
    response = await api.client.post(
        "/api/directory?source=seeded", json=body, headers=api.as_(ADMIN)
    )
    assert response.status_code == 204
    directory = api.services.directory
    assert directory.team_of(user_id="g.nikolaou") == "Legal"
    assert directory.team_of(ip="10.20.3.77") == "Finance"
    assert directory.team_of(user_id="nobody", ip="192.0.2.1") == "Unknown"


async def test_notice_is_public_and_seed_steps_are_remembered(api: Api) -> None:
    notice = (await api.client.get("/api/privacy/notice")).json()
    assert notice["inspected"] and notice["kept"] and notice["never_kept"]
    await api.client.put("/api/demo/seed-state/directory", headers=api.as_(ADMIN))
    await api.client.put("/api/demo/seed-state/directory", headers=api.as_(ADMIN))
    steps = (await api.client.get("/api/demo/seed-state", headers=api.as_(ADMIN))).json()
    assert steps.count("directory") == 1
