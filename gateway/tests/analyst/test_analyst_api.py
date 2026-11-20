from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from gateway.app.analyst.ask import run_readonly
from gateway.app.analyst.questions import EXAMPLES
from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action, Channel, ToolStatus
from gateway.app.events.writer import EventRecord
from gateway.tests.conftest import Api
from gateway.tests.doubles import FakeLLM

EMPLOYEE, ADMIN = DEMO_USERS
BRIEF = EXAMPLES[0]
pytestmark = pytest.mark.integration


def _event(user: str, team: str, tool: str, action: Action, *, days_ago: int = 1) -> EventRecord:
    return EventRecord(
        ts=datetime.now(UTC) - timedelta(days=days_ago),
        user_id=user,
        team=team,
        channel=Channel.PROMPT,
        action=action,
        rule="pii-and-client-data",
        policy_version=1,
        tool=tool,
        tool_status=ToolStatus.UNAPPROVED,
        data_counts={"CLIENT": 1, "AFM": 2},
        origin="log" if action is Action.ALLOW else "gateway",
    )


async def _seed(api: Api) -> None:
    async with api.services.db.session() as session:
        await session.execute(text("TRUNCATE events CASCADE"))
    records = [_event(f"sales-{n}", "Sales", "chatterbox-ai", Action.REDACT) for n in range(4)] + [
        _event(f"legal-{n}", "Legal", "chatterbox-ai", Action.ALLOW) for n in range(3)
    ]
    records.append(_event("lonely", "Tiny", "chatterbox-ai", Action.BLOCK))
    # Small teams are folded by their size in the directory, which only the officer changes.
    people = [
        {"user_id": record.user_id, "display_name": record.user_id, "team": record.team}
        for record in records
    ]
    officer = api.as_(ADMIN)
    await api.client.post("/api/directory", json={"users": people}, headers=officer)
    await api.services.events.write_many(records)


async def test_overview_counts_and_folds_small_teams(api: Api) -> None:
    await _seed(api)
    response = await api.client.get("/api/overview", headers=api.as_(ADMIN))
    overview = response.json()
    assert overview["prompts_inspected"] == 8 and overview["sensitive_share"] == 1.0
    assert {a["action"]: a["count"] for a in overview["actions"]} == {
        "allow": 3,
        "redact": 4,
        "warn": 0,
        "block": 1,
    }
    assert overview["top_unapproved_tools"][0]["count"] == 8
    assert overview["heatmap"]["teams"] == ["Legal", "Other", "Sales"]
    assert len(overview["trend"]) == 14 and sum(p["total"] for p in overview["trend"]) == 8


async def _ask(api: Api, question: str) -> httpx.Response:
    return await api.client.post("/api/ask", json={"question": question}, headers=api.as_(ADMIN))


async def test_ask_runs_the_sql_the_model_wrote_and_returns_its_sentence(
    api: Api, llm: FakeLLM
) -> None:
    await _seed(api)
    chart = {"kind": "bar", "x": "team", "y": ["prompts", "sent_unmasked"]}
    llm.answers["SqlDraft"] = {"sql": BRIEF.sql, "chart": chart}
    llm.completion = " Two teams did, led by Sales. "
    result = (await _ask(api, BRIEF.question)).json()
    assert "v_events" in result["sql"] and result["sql"].endswith("LIMIT 500")
    assert result["columns"] == ["team", "tool", "prompts", "sent_unmasked"]
    assert result["rows"][0] == ["Sales", "Unapproved Tool", 4, 0]
    assert ["Legal", "Unapproved Tool", 3, 3] in result["rows"]
    assert (result["answer"], result["chart"]) == ("Two teams did, led by Sales.", chart)
    (call,) = llm.asked
    assert call.text == BRIEF.question and "v_teams: one row per team" in call.instructions
    assert all(example.question in call.instructions for example in EXAMPLES)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT user_pseudonym FROM events", "The generated query was rejected"),
        ("SELECT no_such_column FROM v_teams", "The generated query failed to run"),
    ],
    ids=["unsafe", "broken"],
)
async def test_sql_from_the_model_that_is_unsafe_or_broken_is_not_answered(
    api: Api, llm: FakeLLM, sql: str, reason: str
) -> None:
    llm.answers["SqlDraft"] = {"sql": sql, "chart": None}
    response = await _ask(api, "Who sent the most prompts?")
    assert response.status_code == 422 and reason in response.json()["detail"]


async def test_readonly_role_cannot_read_tables_or_write(api: Api) -> None:
    readonly_db = api.services.readonly_db
    escapes = (
        "SELECT user_pseudonym FROM events",
        "DELETE FROM v_events",
        "SELECT set_config('role', 'none', true), query_to_xml('select * from events', true, true, '')",  # noqa: E501
        "SELECT rolpassword FROM pg_authid",
        "SELECT pg_read_file('/etc/passwd')",
    )
    for sql in escapes:
        with pytest.raises(DBAPIError):
            await run_readonly(readonly_db, sql)
    columns, _ = await run_readonly(readonly_db, "SELECT team FROM v_teams")
    assert columns == ["team"]


async def test_events_list_has_no_identity_and_employees_are_refused(api: Api) -> None:
    await _seed(api)
    page = (await api.client.get("/api/events?limit=3", headers=api.as_(ADMIN))).json()
    assert page["total"] == 8 and len(page["items"]) == 3
    assert "user_pseudonym" not in page["items"][0] and "user_id" not in page["items"][0]
    refused = await api.client.get("/api/events", headers=api.as_(EMPLOYEE))
    assert refused.status_code == 403
