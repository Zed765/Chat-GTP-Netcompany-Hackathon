import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Principal
from gateway.app.policy.document import MAX_POLICY_BYTES
from gateway.tests.doubles import FakeLLM

SignedIn = Callable[[Principal], dict[str, str]]
EMPLOYEE, ADMIN = DEMO_USERS

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

DEFAULT_POLICY = (Path(__file__).resolve().parents[3] / "policies" / "default.yaml").read_text(
    encoding="utf-8"
)
BROKEN = DEFAULT_POLICY.replace("action: allow", "action: permit")
MODEL_DRAFT = {
    "understood": True,
    "name": "Block source code to unapproved",
    "action": "block",
    "channel": ["prompt"],
    "data": ["SOURCE_CODE"],
    "tool_status": ["unapproved", "unknown"],
    "tool": [],
    "team": [],
    "tainted": None,
    "side_effects": None,
    "destination": None,
    "source": None,
    "suggest_approved_alternative": True,
    "insert_before": None,
    "explanation": "Blocks source code in prompts to tools nobody approved.",
}


async def test_active_policy_and_versions(api: AsyncClient, signed_in: SignedIn) -> None:
    active = await api.get("/api/policy", headers=signed_in(ADMIN))
    assert active.status_code == 200
    body = active.json()
    assert (body["version"], body["active"], body["author"]) == (1, True, "system")
    assert body["yaml"] == DEFAULT_POLICY
    assert body["injection_protection"] == "standard"

    versions = await api.get("/api/policy/versions", headers=signed_in(ADMIN))
    assert [row["version"] for row in versions.json()] == [1]
    assert "yaml" not in versions.json()[0]
    one = await api.get("/api/policy/versions/1", headers=signed_in(ADMIN))
    assert one.json() == body
    missing = await api.get("/api/policy/versions/99", headers=signed_in(ADMIN))
    assert missing.status_code == 404


async def test_the_policy_is_for_analysts(api: AsyncClient, signed_in: SignedIn) -> None:
    assert (await api.get("/api/policy")).status_code == 401
    assert (await api.get("/api/policy", headers=signed_in(EMPLOYEE))).status_code == 403
    for path, body in (
        ("/api/policy/validate", {"yaml": DEFAULT_POLICY}),
        ("/api/policy/activate", {"yaml": DEFAULT_POLICY}),
        ("/api/policy/replay", {"yaml": DEFAULT_POLICY}),
        ("/api/policy/draft", {"yaml": DEFAULT_POLICY, "instruction": "redact IBANs"}),
    ):
        refused = await api.post(path, json=body, headers=signed_in(EMPLOYEE))
        assert refused.status_code == 403, path


async def test_validate(api: AsyncClient, signed_in: SignedIn) -> None:
    headers = signed_in(ADMIN)
    valid = await api.post("/api/policy/validate", json={"yaml": DEFAULT_POLICY}, headers=headers)
    assert valid.json() == {"valid": True, "issues": []}
    invalid = await api.post("/api/policy/validate", json={"yaml": BROKEN}, headers=headers)
    assert invalid.status_code == 200
    assert invalid.json() == {
        "valid": False,
        "issues": [
            {
                "path": "rules[9].action",
                "message": "Must be 'allow', 'redact', 'warn' or 'block'",
                "line": BROKEN.splitlines().index("    action: permit") + 1,
            }
        ],
    }


async def test_draft_replay_and_activate(
    api: AsyncClient, signed_in: SignedIn, llm: FakeLLM
) -> None:
    llm.answers["_ModelDraft"] = MODEL_DRAFT
    headers = signed_in(ADMIN)
    draft = await api.post(
        "/api/policy/draft",
        json={"instruction": "Block source code to unapproved tools", "yaml": DEFAULT_POLICY},
        headers=headers,
    )
    drafted = draft.json()
    assert drafted["rule_name"] == "block-source-code-to-unapproved"
    assert "Block source code to unapproved tools" in llm.texts[0]

    replayed = await api.post(
        "/api/policy/replay", json={"yaml": drafted["yaml"], "days": 7}, headers=headers
    )
    assert replayed.status_code == 200
    assert replayed.json().keys() == {
        "days",
        "events",
        "changed",
        "transitions",
        "by_team",
        "by_tool",
    }

    activated = await api.post(
        "/api/policy/activate",
        json={"yaml": drafted["yaml"], "note": "No source code in unapproved tools"},
        headers=headers,
    )
    assert activated.status_code == 200
    assert (activated.json()["version"], activated.json()["active"]) == (2, True)
    now_active = await api.get("/api/policy", headers=headers)
    assert now_active.json()["yaml"] == drafted["yaml"]
    assert now_active.json()["note"] == "No source code in unapproved tools"


async def test_invalid_policy_is_answered_with_its_issues(
    api: AsyncClient, signed_in: SignedIn
) -> None:
    headers = signed_in(ADMIN)
    for path in ("/api/policy/activate", "/api/policy/replay"):
        refused = await api.post(path, json={"yaml": BROKEN}, headers=headers)
        assert refused.status_code == 400, path
        assert refused.json()["valid"] is False
        assert refused.json()["issues"][0]["path"] == "rules[9].action"
    assert (await api.get("/api/policy", headers=headers)).json()["version"] == 1


async def test_injection_protection_level(api: AsyncClient, signed_in: SignedIn) -> None:
    path = "/api/policy/injection-protection"
    seen_by_employee = await api.get(path, headers=signed_in(EMPLOYEE))
    assert seen_by_employee.json() == {"level": "standard"}
    refused = await api.put(path, json={"level": "off"}, headers=signed_in(EMPLOYEE))
    assert refused.status_code == 403

    changed = await api.put(path, json={"level": "detailed"}, headers=signed_in(ADMIN))
    assert changed.status_code == 200
    assert (changed.json()["version"], changed.json()["injection_protection"]) == (2, "detailed")
    assert "injection_protection: detailed" in changed.json()["yaml"]
    assert (await api.get(path, headers=signed_in(EMPLOYEE))).json() == {"level": "detailed"}


async def test_policy_text_is_never_read_on_the_event_loop(
    api: AsyncClient, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch, llm: FakeLLM
) -> None:
    llm.answers["_ModelDraft"] = MODEL_DRAFT
    loop = asyncio.get_running_loop()
    read = yaml.SafeLoader.get_single_node

    def read_once_the_loop_has_turned(loader: yaml.SafeLoader) -> yaml.Node | None:
        """Stands for a slow read: it only finishes if the event loop is free meanwhile."""
        turned = threading.Event()
        loop.call_soon_threadsafe(turned.set)
        assert turned.wait(timeout=2), "the event loop was held while a policy was read"
        return read(loader)

    monkeypatch.setattr(yaml.SafeLoader, "get_single_node", read_once_the_loop_has_turned)
    headers = signed_in(ADMIN)
    stricter = DEFAULT_POLICY.replace("action: warn", "action: block")
    for path, body in (
        ("/api/policy/validate", {"yaml": DEFAULT_POLICY}),
        ("/api/policy/replay", {"yaml": stricter}),
        ("/api/policy/draft", {"yaml": DEFAULT_POLICY, "instruction": "block IBANs in prompts"}),
        ("/api/policy/activate", {"yaml": stricter}),
    ):
        answered = await api.post(path, json=body, headers=headers)
        assert answered.status_code == 200, path
    assert (await api.get("/api/policy", headers=headers)).json()["version"] == 2
    assert (await api.get("/api/policy/versions/1", headers=headers)).status_code == 200
    changed = await api.put(
        "/api/policy/injection-protection", json={"level": "off"}, headers=headers
    )
    assert changed.json()["version"] == 3


async def test_an_oversized_or_aliased_policy_is_refused_by_every_route(
    api: AsyncClient, signed_in: SignedIn
) -> None:
    headers = signed_in(ADMIN)
    too_large = DEFAULT_POLICY + "# padding\n" * (MAX_POLICY_BYTES // 10)
    aliased = DEFAULT_POLICY + "extra: &a [x]\nmore: [*a, *a]\n"
    for text, message in ((too_large, "larger than 64 KB"), (aliased, "Anchors and aliases")):
        validated = await api.post("/api/policy/validate", json={"yaml": text}, headers=headers)
        assert validated.status_code == 200 and validated.json()["valid"] is False
        assert message in validated.json()["issues"][0]["message"]
        for path in ("/api/policy/activate", "/api/policy/replay"):
            refused = await api.post(path, json={"yaml": text}, headers=headers)
            assert refused.status_code == 400, path
            assert message in refused.json()["issues"][0]["message"]
        drafted = await api.post(
            "/api/policy/draft",
            json={"yaml": text, "instruction": "block IBANs in prompts"},
            headers=headers,
        )
        assert drafted.json()["rule_name"] is None and drafted.json()["yaml"] == text
    assert (await api.get("/api/policy", headers=headers)).json()["version"] == 1
