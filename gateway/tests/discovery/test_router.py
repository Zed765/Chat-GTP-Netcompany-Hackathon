from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Principal
from gateway.app.discovery import InventoryService

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

SignedIn = Callable[[Principal], dict[str, str]]
EMPLOYEE, ADMIN = DEMO_USERS
YESTERDAY = datetime.now(UTC) - timedelta(days=1)
PROXY_LOG = (
    "".join(
        f"{YESTERDAY.timestamp():.3f} 120 10.20.1.15 TCP_TUNNEL/200 900 CONNECT {host}:443 "
        "- HIER_DIRECT/203.0.113.9 -\n"
        for host in ("chatgpt.com", "chatgpt.com", "promptforge.example", "parcelpost.example")
    )
    + "damaged line\n"
)


async def test_everyone_signed_in_can_read_the_inventory(
    api: AsyncClient, signed_in: SignedIn
) -> None:
    assert (await api.get("/api/tools")).status_code == 401
    listed = await api.get("/api/tools", headers=signed_in(EMPLOYEE))
    assert listed.status_code == 200
    tools = listed.json()
    assert len(tools) >= 29
    names = [tool["name"] for tool in tools]
    assert names == sorted(names, key=str.lower)
    assert {tool["rating_source"] for tool in tools} == {"seeded"}

    demo = await api.get("/api/tools", params={"demo_only": True}, headers=signed_in(EMPLOYEE))
    assert [(tool["slug"], tool["status"], tool["is_demo"]) for tool in demo.json()] == [
        ("athena-assist", "approved", True),
        ("draftpilot", "tolerated", True),
        ("chatterbox-ai", "unapproved", True),
    ]

    one = await api.get("/api/tools/deepl", headers=signed_in(EMPLOYEE))
    assert one.json() == {
        "slug": "deepl",
        "name": "DeepL",
        "domains": ["deepl.com"],
        "category": "translation",
        "description": "Machine translation for text and documents.",
        "status": "approved",
        "risk_score": 2,
        "risk_factors": {
            "trains_on_customer_data": False,
            "retention_days": 0,
            "data_residency": "EU",
            "enterprise_terms": True,
            "sso": True,
            "certifications": ["ISO 27001"],
        },
        "rating_source": "seeded",
        "needs_review": False,
        "review_note": None,
        "is_demo": False,
        "first_seen": None,
        "last_seen": None,
        "requests_14d": 0,
        "usage_by_team": [],
    }
    assert (await api.get("/api/tools/nope", headers=signed_in(EMPLOYEE))).status_code == 404


async def test_only_an_analyst_changes_a_tool(
    api: AsyncClient, signed_in: SignedIn, inventory: InventoryService
) -> None:
    change = {"status": "approved", "risk_factors": {"sso": True, "certifications": ["SOC 2"]}}
    for user in (EMPLOYEE,):
        refused = await api.patch("/api/tools/claude", json=change, headers=signed_in(user))
        assert refused.status_code == 403

    changed = await api.patch("/api/tools/claude", json=change, headers=signed_in(ADMIN))

    assert changed.status_code == 200
    body = changed.json()
    assert (body["status"], body["rating_source"]) == ("approved", "analyst_confirmed")
    assert body["risk_factors"]["certifications"] == ["SOC 2"]
    assert (await inventory.resolve("claude.ai")).status.value == "approved"
    out_of_range = await api.patch(
        "/api/tools/claude", json={"risk_score": 9}, headers=signed_in(ADMIN)
    )
    assert out_of_range.status_code == 422
    missing = await api.patch("/api/tools/nope", json=change, headers=signed_in(ADMIN))
    assert missing.status_code == 404


async def test_uploading_a_log_updates_usage_and_fills_the_review_queue(
    api: AsyncClient, signed_in: SignedIn
) -> None:
    analyst = signed_in(ADMIN)
    assert (await api.get("/api/discovery/queue", headers=analyst)).json() == []
    upload = {"file": ("access.log", PROXY_LOG.encode(), "text/plain")}
    refused = await api.post("/api/discovery/logs", files=upload, headers=signed_in(EMPLOYEE))
    assert refused.status_code == 403

    uploaded = await api.post("/api/discovery/logs", files=upload, headers=analyst)

    assert uploaded.status_code == 200
    result = uploaded.json()
    assert (result["filename"], result["kind"], result["duplicate"]) == (
        "access.log",
        "squid",
        False,
    )
    assert (result["lines"], result["malformed"], result["matched"]) == (5, 1, 3)
    assert result["new_tool_slugs"] == ["promptforge-example"]

    chatgpt = await api.get("/api/tools/chatgpt", headers=analyst)
    assert chatgpt.json()["requests_14d"] == 2
    assert chatgpt.json()["usage_by_team"] == [{"team": "Sales", "requests": 2}]
    queue = (await api.get("/api/discovery/queue", headers=analyst)).json()
    assert [(tool["slug"], tool["status"], tool["needs_review"]) for tool in queue] == [
        ("promptforge-example", "unknown", True)
    ]
    assert queue[0]["rating_source"] == "model_drafted"

    # The analyst bans it: it leaves the queue and stays in the inventory.
    banned = await api.patch(
        "/api/tools/promptforge-example", json={"status": "unapproved"}, headers=analyst
    )
    assert (banned.json()["status"], banned.json()["needs_review"]) == ("unapproved", False)
    assert (await api.get("/api/discovery/queue", headers=analyst)).json() == []

    again = await api.post("/api/discovery/logs", files=upload, headers=analyst)
    assert again.json()["duplicate"] is True
    ingestions = (await api.get("/api/discovery/ingestions", headers=analyst)).json()
    assert [(row["id"], row["filename"], row["new_tools"]) for row in ingestions] == [
        (result["id"], "access.log", 1)
    ]


async def test_dns_upload_and_bad_uploads(api: AsyncClient, signed_in: SignedIn) -> None:
    analyst = signed_in(ADMIN)
    dns = f"{YESTERDAY.isoformat()} 10.20.4.8 claude.ai. A\n".encode()
    uploaded = await api.post(
        "/api/discovery/logs",
        files={"file": ("queries.dns", dns, "text/plain")},
        data={"kind": "dns"},
        headers=analyst,
    )
    assert (uploaded.json()["kind"], uploaded.json()["matched"]) == ("dns", 1)

    empty = await api.post(
        "/api/discovery/logs", files={"file": ("empty.log", b"  \n", "text/plain")}, headers=analyst
    )
    assert (empty.status_code, empty.json()["detail"]) == (400, "The log file is empty")
    wrong_kind = await api.post(
        "/api/discovery/logs",
        files={"file": ("x.log", b"x", "text/plain")},
        data={"kind": "netflow"},
        headers=analyst,
    )
    assert wrong_kind.status_code == 422
