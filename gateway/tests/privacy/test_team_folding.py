"""Small-team folding follows the directory, and imported history is marked as imported."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action, Channel
from gateway.app.events.writer import EventRecord
from gateway.app.privacy.directory import DirectoryImport
from gateway.tests.conftest import Api

EMPLOYEE, ADMIN = DEMO_USERS
AFM = "094014201"
pytestmark = pytest.mark.integration


@pytest.fixture
async def uploaded_directory(api: Api) -> AsyncIterator[None]:
    """Leaves the uploaded part of the directory empty again, for the tests that follow."""
    yield
    await api.services.directory.replace("uploaded", DirectoryImport())
    await api.services.directory.reload()


def _event(user_id: str, team: str) -> EventRecord:
    return EventRecord(
        user_id=user_id,
        team=team,
        channel=Channel.PROMPT,
        action=Action.REDACT,
        rule="pii-and-client-data",
        policy_version=1,
        data_counts={"AFM": 1},
    )


async def _shown_team(api: Api, event_id: int) -> str:
    shown = await api.client.get(f"/api/events/{event_id}", headers=api.as_(ADMIN))
    return str(shown.json()["team"])


def _colleagues(team: str) -> dict[str, list[dict[str, str]]]:
    return {
        "users": [
            {"user_id": f"{team.lower()}-{n}", "display_name": f"{team} {n}", "team": team}
            for n in range(1, 4)
        ]
    }


async def test_only_the_data_protection_officer_may_change_the_directory(
    api: Api, uploaded_directory: None
) -> None:
    for refused in (EMPLOYEE,):
        response = await api.client.post(
            "/api/directory", json=_colleagues("Compliance"), headers=api.as_(refused)
        )
        assert response.status_code == 403
    assert api.services.directory.team_of(user_id="compliance-1") == "Unknown"

    accepted = await api.client.post(
        "/api/directory", json=_colleagues("Platform"), headers=api.as_(ADMIN)
    )
    assert accepted.status_code == 204
    assert api.services.directory.team_of(user_id="platform-1") == "Platform"


async def test_events_under_other_user_ids_do_not_name_a_team_of_one(api: Api) -> None:
    """The officer is alone in her team, whatever events exist under her team's name."""
    events = [
        await api.services.events.write(_event(user_id, ADMIN.team))
        for user_id in (ADMIN.user_id, "made-up-1", "made-up-2")
    ]
    assert {await _shown_team(api, event_id) for event_id in events} == {"Other"}


async def test_a_team_is_named_once_the_directory_lists_three_people(
    api: Api, uploaded_directory: None
) -> None:
    event_id = await api.services.events.write(_event("platform-1", "Platform"))
    assert await _shown_team(api, event_id) == "Other"
    await api.client.post("/api/directory", json=_colleagues("Platform"), headers=api.as_(ADMIN))
    assert await _shown_team(api, event_id) == "Platform"


async def test_ingestion_never_claims_the_gateway_was_in_the_path(api: Api) -> None:
    analyst = api.as_(ADMIN)
    now = datetime.now(UTC).isoformat()
    sent = {"ts": now, "user_id": "imported-history", "tool": "chatterbox-ai"}
    records = [
        {**sent, "text": f"Send the invoice for tax number {AFM}", "enforced": True},
        {**sent, "text": "What is the capital of France?"},
    ]
    refused = await api.client.post("/api/ingest/prompts", json=records, headers=api.as_(EMPLOYEE))
    assert refused.status_code == 403

    response = await api.client.post("/api/ingest/prompts", json=records, headers=analyst)

    assert response.status_code == 200 and response.json()["ingested"] == 2
    async with api.services.db.session() as session:
        origins = await session.scalars(
            text("SELECT origin FROM events WHERE user_pseudonym = :user ORDER BY origin"),
            {"user": api.services.events.pseudonym("imported-history")},
        )
        assert list(origins) == ["import", "log"]
