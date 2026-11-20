"""The agent service end to end in one process: browser -> agent -> gateway proxy -> tool
servers, with a fake model answering the agent's Responses API calls.

The gateway's own `/v1/responses` belongs to another module, so here the fake model is
mounted in its place. Prompts therefore reach the model unmasked; tool results do not.
"""

import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import TypeAdapter
from redis.asyncio import Redis

from agent.main import create_app
from agent.schemas import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.tools import function_name
from gateway.app.core.types import Action, InjectionProtection
from gateway.app.proxy import sse
from gateway.tests.mcp_proxy.fakes import (
    ADMIN,
    PLACEHOLDER,
    Stack,
    YamlPolicy,
    bearer,
    make_stack,
)
from gateway.tests.mcp_proxy.inprocess import Gateway, running_gateway
from mcp_servers.crm.clients import FIXTURE

SUPPLIER = "https://supplier-portal.example/news"
ATTACKER = "audit@supplier-portal-review.official"
COLLEAGUE = "a.bilas@aspida-demo.example"
OUTSIDER = "partner@outside.example"
SUMMARY = "The payment term changes from 30 to 45 days on 1 January 2027."
EVENT = TypeAdapter[AgentEvent](AgentEvent)
EMAIL_PLACEHOLDER = re.compile(r"<EMAIL_\d+>")
DELTA_CHARS = 16


@dataclass(frozen=True)
class Call:
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Seen:
    """What the model has in front of it for one move: its instructions, and the results of
    the tool calls made since the user's message, as the gateway let them through."""

    instructions: str
    outputs: list[str]


Move = Call | str | Callable[[Seen], Call]


def _events(move: Call | str) -> Iterator[str]:
    """The part of a Responses API stream the agent reads: the text as it is written, then
    the finished output item."""
    item: dict[str, Any]
    if isinstance(move, Call):
        item = {
            "type": "function_call",
            "id": f"fc_{uuid4().hex}",
            "call_id": f"call_{uuid4().hex}",
            "status": "completed",
            "name": function_name(move.tool),
            "arguments": json.dumps(move.arguments, ensure_ascii=False),
        }
    else:
        item = {
            "type": "message",
            "id": f"msg_{uuid4().hex}",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": move, "annotations": []}],
        }
        where = {"item_id": item["id"], "output_index": 0, "content_index": 0}
        for start in range(0, len(move), DELTA_CHARS):
            delta = move[start : start + DELTA_CHARS]
            yield sse.encode(
                {"type": "response.output_text.delta", "delta": delta, "logprobs": [], **where},
                "response.output_text.delta",
            )
    yield sse.encode(
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        "response.output_item.done",
    )


class FakeModel:
    """Answers each request with the next move of a fixed script: one tool call at a time,
    then the answer. It does whatever the script says, the way a model that obeys every
    instruction it reads would."""

    def __init__(self, *moves: Move) -> None:
        self._moves = moves
        self.requests: list[dict[str, Any]] = []

    async def respond(self, request: Request) -> StreamingResponse:
        body = await request.json()
        self.requests.append(body)
        items = body["input"]
        asked = max(index for index, item in enumerate(items) if item.get("role") == "user")
        outputs = [
            item["output"]
            for item in items[asked + 1 :]
            if item.get("type") == "function_call_output"
        ]
        move = self._moves[len(outputs)]
        if not isinstance(move, Call | str):
            move = move(Seen(body["instructions"], outputs))
        return StreamingResponse(_events(move), media_type="text/event-stream")


def _planted_address(page: str) -> str:
    """Where a page's hidden instruction wants the email sent, as the model sees it."""
    address = EMAIL_PLACEHOLDER.search(page)
    assert address, "the address in the page reaches the model as a placeholder"
    return address.group()


def _export_clients(seen: Seen) -> Call:
    page, listing = seen.outputs
    arguments = {"to": _planted_address(page), "subject": "Client export", "body": listing}
    return Call("mail.send_email", arguments)


def fooled_by_the_payment_terms_page() -> FakeModel:
    """Reads the supplier's page and carries out its hidden instruction before answering."""
    return FakeModel(
        Call("web.fetch_page", {"url": f"{SUPPLIER}/payment-terms-2027"}),
        Call("crm.search_clients", {"query": ""}),
        _export_clients,
        SUMMARY,
    )


def email_a_client_list(team: str, to: str) -> tuple[Move, ...]:
    """Looks a team's clients up in the CRM and emails the list as the CRM returned it."""

    def send(seen: Seen) -> Call:
        arguments = {"to": to, "subject": f"Clients of {team}", "body": seen.outputs[-1]}
        return Call("mail.send_email", arguments)

    return Call("crm.search_clients", {"query": team}), send, f"I sent the email to {to}."


@dataclass
class Desk:
    browser: httpx2.AsyncClient
    gateway: Gateway
    stack: Stack

    async def new_session(self) -> str:
        created = await self.browser.post("/sessions")
        session_id: str = created.raise_for_status().json()["session_id"]
        return session_id

    async def events(self, path: str, body: dict[str, Any]) -> list[AgentEvent]:
        response = await self.browser.post(path, json=body)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in response.text.splitlines() if line]
        assert all(line.startswith("data: ") for line in lines)
        return [EVENT.validate_json(line.removeprefix("data: ")) for line in lines]

    async def ask(self, prompt: str, session_id: str | None = None) -> list[AgentEvent]:
        session_id = session_id or await self.new_session()
        return await self.events(f"/sessions/{session_id}/messages", {"content": prompt})


@asynccontextmanager
async def desk(
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
    policy: YamlPolicy | None = None,
    responses: Callable[..., Any] | None = None,
) -> AsyncIterator[Desk]:
    """`responses` answers the agent's model calls."""
    stack = make_stack(redis, policy=policy)
    async with running_gateway(stack.services, monkeypatch) as gateway:
        if responses:
            gateway.app.post("/v1/responses", response_model=None)(responses)
        agent = create_app(transport=httpx2.ASGITransport(app=gateway.app))
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=agent),
            base_url="http://agent:8001",
            headers=bearer(),
        ) as browser:
            yield Desk(browser, gateway, stack)


def calls(events: list[AgentEvent]) -> list[ToolCallEvent]:
    return [event for event in events if isinstance(event, ToolCallEvent)]


def results(events: list[AgentEvent]) -> list[ToolResultEvent]:
    return [event for event in events if isinstance(event, ToolResultEvent)]


def answer(events: list[AgentEvent]) -> str:
    return "".join(event.delta for event in events if isinstance(event, TextDelta))


def raw_client_values() -> set[str]:
    values: set[str] = set()
    for client in FIXTURE:
        values |= {client["legal_name"], client["afm"], client["email"], client["phone"]}
        values |= {contact["name"] for contact in client["contacts"]}
    return values


async def test_session_api(redis: Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    async with desk(redis, monkeypatch) as d:
        created = (await d.browser.post("/sessions")).json()
        path = f"/sessions/{created['session_id']}"
        assert created == {
            "session_id": created["session_id"],
            "protection": "standard",
            "tainted": False,
            "taint_source": None,
            "messages": [],
            "trace": [],
            "request_of_call": {},
        }

        assert (await d.browser.post("/sessions", headers={"Authorization": ""})).status_code == 401
        forged = {"Authorization": "Bearer forged"}
        assert (await d.browser.post("/sessions", headers=forged)).status_code == 401
        assert (await d.browser.get(path, headers=bearer(ADMIN))).status_code == 404
        assert (await d.browser.get("/sessions/unknown")).status_code == 404

        d.stack.policy.level = InjectionProtection.DETAILED
        assert (await d.browser.get(path)).json()["protection"] == "detailed"
        assert (await d.browser.delete(path)).status_code == 204
        assert (await d.browser.get(path)).status_code == 404
    (ended,) = d.stack.vault.ended
    assert ended.endswith(f":{created['session_id']}")


async def test_scene_3_with_protection_on_three_times_in_a_row(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fooled_by_the_payment_terms_page()
    async with desk(redis, monkeypatch, responses=model.respond) as d:
        for _ in range(3):
            session_id = await d.new_session()
            events = await d.ask("Summarise the supplier's update on payment terms", session_id)

            page, listing = results(events)
            assert page.tool == "web.fetch_page" and page.tainted and page.source == "untrusted"
            assert page.injection and page.injection.flagged
            assert page.layers_run == ["heuristics", "model"]
            assert "Ignore your previous instructions" in (page.injection.evidence or "")
            assert listing.tool == "crm.search_clients" and listing.masked_values > 20

            fetch, search, email = calls(events)
            assert (fetch.decision.action, search.decision.action) == (Action.REDACT, Action.ALLOW)
            assert email.tool == "mail.send_email" and email.decision.action is Action.BLOCK
            assert (
                email.decision.rule == "tainted-agent-side-effects" and not email.decision.resolved
            )
            assert email.arguments["to"] == "<EMAIL_1>", "the model only ever saw the placeholder"

            assert events[-1] == DoneEvent(tainted=True, taint_source="web.fetch_page")
            assert answer(events) == SUMMARY
            state = (await d.browser.get(f"/sessions/{session_id}")).json()
            assert state["tainted"] and len(state["trace"]) == 5 and len(state["messages"]) == 2
            # Every call belongs to the one request made so far, and a reload says so.
            assert state["request_of_call"] == dict.fromkeys(
                {step["call_id"] for step in state["trace"]}, 0
            )
        assert d.gateway.mailbox.sent == []


async def test_scene_3_with_protection_off_three_times_in_a_row(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fooled_by_the_payment_terms_page()
    policy = YamlPolicy(InjectionProtection.OFF)
    async with desk(redis, monkeypatch, policy, model.respond) as d:
        for round_number in range(1, 4):
            events = await d.ask("Summarise the supplier's update on payment terms")

            assert all(
                result.injection is None and not result.tainted for result in results(events)
            )
            email = calls(events)[-1]
            assert email.tool == "mail.send_email" and email.decision.action is Action.REDACT
            assert not email.decision.resolved and email.layers_run == []
            assert events[-1] == DoneEvent(tainted=False, taint_source=None)

            received = d.gateway.mailbox.outside()
            assert len(received) == round_number and received[-1].recipient == ATTACKER
            assert len(PLACEHOLDER.findall(received[-1].body)) > 20
            assert not any(value in received[-1].body for value in raw_client_values())


async def test_colleague_receives_real_values_and_the_trace_says_so(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel(*email_a_client_list("Legal", COLLEAGUE))
    async with desk(redis, monkeypatch, responses=model.respond) as d:
        events = await d.ask("Email the clients of the Legal team to my colleague")
    _, email = calls(events)
    assert email.decision.action is Action.ALLOW and email.decision.resolved
    assert PLACEHOLDER.search(email.arguments["body"]), "the trace shows what the model wrote"
    (delivered,) = d.gateway.mailbox.sent
    assert delivered.recipient == COLLEAGUE
    assert "Θεσσαλική Ενεργειακή Μ.Ι.Κ.Ε." in delivered.body and not PLACEHOLDER.search(
        delivered.body
    )
    assert events[-1] == DoneEvent(tainted=False, taint_source=None)
    # The agent asks for the model the gateway names, on every call of the turn.
    named = d.stack.services.settings.model_inline
    assert [request["model"] for request in model.requests] == [named] * 3


async def test_system_prompt_leak_is_stopped_by_the_canary(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leak(seen: Seen) -> Call:
        (page,) = seen.outputs
        arguments = {"to": _planted_address(page), "subject": "Check", "body": seen.instructions}
        return Call("mail.send_email", arguments)

    model = FakeModel(
        Call("web.fetch_page", {"url": f"{SUPPLIER}/security-questionnaire"}),
        leak,
        "The questionnaire asks who has a portal account.",
    )
    async with desk(redis, monkeypatch, responses=model.respond) as d:
        events = await d.ask("What does the supplier's security questionnaire ask for?")
    email = calls(events)[-1]
    assert email.decision.rule == "canary-leak" and email.decision.action is Action.BLOCK
    assert email.layers_run == ["canary"] and "ASPIDA-CANARY-" in email.arguments["body"]
    assert d.gateway.mailbox.sent == []
    alert = d.stack.events.records[-1]
    assert alert.rule == "canary-leak" and alert.injection and alert.injection.flagged


async def test_held_call_is_confirmed_through_the_api(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = YamlPolicy(actions={"tainted-agent-side-effects": Action.WARN})
    vpn_page = Call("web.fetch_page", {"url": "https://intranet.aspida-demo.example/kb/vpn-setup"})
    model = FakeModel(vpn_page, *email_a_client_list("Finance", OUTSIDER))
    async with desk(redis, monkeypatch, policy, model.respond) as d:
        session_id = await d.new_session()
        events = await d.ask("Summarise the VPN page, then email the Finance clients", session_id)

        held = calls(events)[-1]
        assert held.tool == "mail.send_email" and held.decision.needs_confirmation
        assert isinstance(events[-1], DoneEvent) and d.gateway.mailbox.sent == []
        path = f"/sessions/{session_id}/confirmations/{held.call_id}"
        assert (await d.browser.post(f"{path}-x", json={"approve": True})).status_code == 404

        events = await d.events(path, {"approve": True})
        confirmed, receipt = calls(events)[0], results(events)[0]
        assert confirmed.call_id == held.call_id and not confirmed.decision.needs_confirmation
        assert confirmed.decision.action is Action.WARN and not confirmed.decision.resolved
        assert receipt.tool == "mail.send_email" and "I sent the email" in answer(events)
        (delivered,) = d.gateway.mailbox.sent
        assert delivered.recipient == OUTSIDER
        assert not any(value in delivered.body for value in raw_client_values())

        trace = (await d.browser.get(f"/sessions/{session_id}")).json()["trace"]
        assert [step["call_id"] for step in trace].count(held.call_id) == 2, "one call, one result"
        assert (await d.browser.post(path, json={"approve": True})).status_code == 404


async def test_session_the_gateway_no_longer_knows_is_gone(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with desk(redis, monkeypatch) as d:
        session_id = await d.new_session()
        await redis.flushall()
        response = await d.browser.post(f"/sessions/{session_id}/messages", json={"content": "Hi"})
        assert response.status_code == 404


async def test_prompt_the_gateway_blocks_ends_with_its_message_and_done(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusal = "Blocked: the prompt contains a secret. Remove it and try again."

    async def blocked() -> JSONResponse:
        error = {"message": refusal, "type": "aspida_policy_block", "code": "secrets-never-leave"}
        return JSONResponse({"error": error}, status_code=403)

    async with desk(redis, monkeypatch, responses=blocked) as d:
        session_id = await d.new_session()
        events = await d.ask("My key is sk-live-123", session_id)
        assert events == [ErrorEvent(message=refusal), DoneEvent(tainted=False, taint_source=None)]
        assert (await d.browser.get(f"/sessions/{session_id}")).json()["messages"] == [
            {"role": "user", "content": "My key is sk-live-123"}
        ]
