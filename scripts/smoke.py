"""End-to-end smoke test against the running stack: `make smoke`.

Runs inside the gateway container and goes through the web container, the way a browser
does. It covers the employee and admin scenes and checks that no raw value was stored on the
way. The models answer for real, so it asserts what the gateway does with a request and
never the wording of an answer. The agent scene depends on what the model decides to do, so
it is not checked here.
"""

import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gateway.app.config import get_settings

WEB = "http://web:8080"
MOCK_UPSTREAM = "http://mock-upstream:9100"
PAGES = ("/", "/chat", "/agent", "/overview", "/configure", "/attacker-inbox")
SERVICES = {
    "web": f"{WEB}/healthz",
    "gateway": "http://gateway:8000/healthz",
    "agent": f"{WEB}/agent-api/healthz",
    "mock-upstream": f"{MOCK_UPSTREAM}/healthz",
    "mcp-crm": "http://mcp-crm:9001/healthz",
    "mcp-mail": "http://mcp-mail:9002/healthz",
    "mcp-web": "http://mcp-web:9003/healthz",
}
SCENE_1 = ("chat-client-email-unapproved-en", "chat-client-email-unapproved-el")
BRIEF_QUESTION = "Which teams sent client data to unapproved AI tools this week?"
ANALYST_VIEWS = ("v_events", "v_tools", "v_teams")
MIN_SECRET_CHARS = 8


class Stack:
    """The running stack, with one signed-in session per demo role."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        users = client.get(f"{WEB}/api/demo/users").raise_for_status().json()
        self.tokens = {
            user["role"]: client.post(f"{WEB}/api/demo/login", json={"user_id": user["user_id"]})
            .raise_for_status()
            .json()["token"]
            for user in users
        }
        self.seeded = client.get(f"{WEB}/api/meta").json()["seed_demo_data"]
        # Values seen in prompts during the run; none may be stored anywhere afterwards.
        self.raw_values: set[str] = set()

    def call(self, role: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.tokens[role]}", **kwargs.pop("headers", {})}
        return self.client.request(method, f"{WEB}{path}", headers=headers, **kwargs)

    def examples(self, page: str) -> dict[str, dict[str, Any]]:
        listed = self.call("employee", "GET", f"/api/examples?page={page}").json()
        return {example["id"]: example for example in listed}

    def chat(self, example: dict[str, Any], **headers: str) -> httpx.Response:
        body = {
            "model": example["tool"],
            "messages": [{"role": "user", "content": example["prompt"]}],
        }
        sent = {"X-Aspida-Tool": example["tool"], "X-Aspida-Conversation": f"smoke-{example['id']}"}
        return self.call(
            "employee", "POST", "/v1/chat/completions", json=body, headers=sent | headers
        )


def check_services(stack: Stack) -> None:
    for name, url in SERVICES.items():
        assert stack.client.get(url).status_code == 200, f"{name} is not healthy"


def check_pages(stack: Stack) -> None:
    for page in PAGES:
        response = stack.client.get(f"{WEB}{page}")
        assert response.status_code == 200 and '<div id="root">' in response.text, page


def check_sign_in(stack: Stack) -> None:
    assert stack.client.get(f"{WEB}/api/overview").status_code == 401
    assert set(stack.tokens) == {"employee", "admin"}
    assert stack.call("admin", "GET", "/api/overview").status_code == 200
    refused = stack.call("employee", "GET", "/api/overview").status_code
    assert refused == 403, "an employee must not read the dashboard"


def check_scene_1_employee(stack: Stack) -> None:
    """A client email is masked for the AI tool, and no placeholder is left in the answer,
    in two languages."""
    examples = stack.examples("chat")
    stack.client.delete(f"{MOCK_UPSTREAM}/recordings")
    for example_id in SCENE_1:
        example = examples[example_id]
        response = stack.chat(example)
        assert response.status_code == 200, f"{example_id}: HTTP {response.status_code}"
        body = response.json()
        trace = body["aspida"]
        values = {example["prompt"][span["start"] : span["end"]] for span in trace["spans"]}
        kinds = {span["data_type"] for span in trace["spans"]}
        assert trace["action"] == "redact", f"{example_id}: {trace['action']}"
        assert {"AFM", "IBAN"} <= kinds and kinds & {"PERSON", "CLIENT"}, sorted(kinds)
        seen = json.dumps(trace["upstream_messages"], ensure_ascii=False)
        assert not any(value in seen for value in values), f"{example_id}: value in the trace"
        placeholders = {span["placeholder"] for span in trace["spans"] if span["placeholder"]}
        assert placeholders and all(placeholder in seen for placeholder in placeholders)
        answer = body["choices"][0]["message"]["content"] or ""
        left = sorted(placeholder for placeholder in placeholders if placeholder in answer)
        assert not left, f"{example_id}: placeholders left in the answer: {left}"
        assert trace["explanation"]["summary"], f"{example_id}: no explanation"
        stack.raw_values |= values
    recorded = stack.client.get(f"{MOCK_UPSTREAM}/recordings").text
    leaked = sorted(value for value in stack.raw_values if value in recorded)
    assert not leaked, f"the AI tool received real values: {leaked}"


def check_four_actions(stack: Stack) -> None:
    """Every Chat example ends in the action it promises, and a warning can be acknowledged."""
    examples = stack.examples("chat")
    seen: set[str] = set()
    for example in examples.values():
        response = stack.chat(example)
        action = (response.json().get("aspida") or {}).get("action")
        assert action == example["expected"], (
            f"{example['id']}: {action}, not {example['expected']}"
        )
        seen.add(action)
        if action == "warn":
            assert response.status_code == 409
            trace_id = response.json()["aspida"]["trace_id"]
            confirmed = stack.chat(example, **{"X-Aspida-Acknowledge-Warning": trace_id})
            assert confirmed.status_code == 200, "an acknowledged warning must be sent"
        if action == "block":
            assert response.status_code == 403
    assert seen == {"allow", "redact", "warn", "block"}, f"only {sorted(seen)} were shown"


def check_scene_2_admin(stack: Stack) -> None:
    """The brief's question comes back as a table, with the guarded SQL that produced it."""
    response = stack.call("admin", "POST", "/api/ask", json={"question": BRIEF_QUESTION})
    assert response.status_code == 200, response.text
    result = response.json()
    sql = result["sql"].lower()
    assert "select" in sql and any(view in sql for view in ANALYST_VIEWS), result["sql"]
    assert result["columns"], "the answer has no table"
    assert all(len(row) == len(result["columns"]) for row in result["rows"])


def check_demo_data(stack: Stack) -> None:
    """On first boot the dashboard and the three stores are filled."""
    summary = stack.call("admin", "GET", "/api/protected/summary").json()
    rows = {
        (store["store"], layer["source"]): layer["rows"]
        for store in summary["stores"]
        for layer in store["layers"]
    }
    for store in ("terms", "fingerprints", "patterns"):
        assert rows[(store, "default")] > 0, f"the default pack has no {store}"
    if not stack.seeded:
        return
    assert rows[("terms", "synced")] > 0 and rows[("fingerprints", "seeded")] > 0
    assert rows[("patterns", "seeded")] > 0
    overview = stack.call("admin", "GET", "/api/overview").json()
    assert overview["prompts_inspected"] > 1000, "the dashboard is not populated"


async def stored_values(values: set[str]) -> list[str]:
    """Where any of the values is stored: a Postgres table or a Redis key."""
    settings = get_settings()
    found: list[str] = []
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        tables = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        for (table,) in tables.all():
            for value in values:
                hits = await connection.scalar(
                    text(f'SELECT count(*) FROM "{table}" AS t WHERE t::text LIKE :needle'),  # noqa: S608
                    {"needle": f"%{value}%"},
                )
                if hits:
                    found.append(f"{table}: {hits} rows hold a raw value")
                    break
    await engine.dispose()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async for key in redis.scan_iter():
        kind = await redis.type(key)
        stored = await (redis.hgetall(key) if kind == "hash" else redis.get(key))
        dumped = f"{key} {json.dumps(stored, ensure_ascii=False)}"
        if any(value in dumped for value in values):
            found.append(f"redis key {key} holds a raw value")
    await redis.aclose()
    return found


def check_nothing_raw_is_stored(stack: Stack) -> None:
    """The values typed in scene 1 are in no Postgres table and no Redis key."""
    values = {value for value in stack.raw_values if len(value) >= MIN_SECRET_CHARS}
    assert values, "scene 1 has to run first"
    found = asyncio.run(stored_values(values))
    assert not found, "; ".join(found)


CHECKS: tuple[Callable[[Stack], None], ...] = (
    check_services,
    check_pages,
    check_sign_in,
    check_demo_data,
    check_scene_1_employee,
    check_four_actions,
    check_scene_2_admin,
    check_nothing_raw_is_stored,
)


def main() -> int:
    failures = 0
    with httpx.Client(timeout=120) as client:
        stack = Stack(client)
        for check in CHECKS:
            try:
                check(stack)
            except (AssertionError, httpx.HTTPError, KeyError) as exc:
                failures += 1
                print(f"FAIL {check.__name__}: {exc!r}")
            else:
                print(f"ok   {check.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
