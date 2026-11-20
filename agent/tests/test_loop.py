"""The agent loop with a fake model and a recording toolbox: no gateway, no network."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agent.loop import DECLINED, PREVIEW_CHARS, SUPERSEDED, confirmation_turn, user_turn
from agent.model import Delta, Output
from agent.schemas import (
    AgentEvent,
    ErrorEvent,
    TextDelta,
    ToolCallEvent,
    ToolDecision,
    ToolResultEvent,
)
from agent.sessions import Session
from agent.tools import Inspection, ResultReport, ToolOutcome
from gateway.app.core.types import Action, InjectionVerdict, Trust

CANARY = "ASPIDA-CANARY-00ff00ff00ff00ff"
ALLOWED = ToolDecision(action=Action.ALLOW, rule="default", reason="Allowed.", resolved=True)
BLOCKED = ToolDecision(
    action=Action.BLOCK, rule="tainted-agent-side-effects", reason="Tainted.", resolved=False
)
HELD = ToolDecision(
    action=Action.WARN,
    rule="confirm-writes",
    reason="Check.",
    resolved=False,
    needs_confirmation=True,
)


def call_item(call_id: str, function: str, **arguments: Any) -> dict[str, Any]:
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": function,
        "arguments": json.dumps(arguments),
    }


def message_item(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


@dataclass
class FakeModel:
    """Answers each call with the next prepared response and records what it was sent."""

    responses: list[list[dict[str, Any]]]
    seen: list[dict[str, Any]] = field(default_factory=list)

    async def respond(
        self, *, instructions: str, items: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Delta | Output]:
        self.seen.append({"instructions": instructions, "items": list(items), "tools": tools})
        output = self.responses.pop(0)
        for item in output:
            if item["type"] == "message":
                text = item["content"][0]["text"]
                for start in range(0, len(text), 5):
                    yield Delta(text[start : start + 5])
        yield Output(output)


@dataclass
class FakeTools:
    outcomes: dict[str, ToolOutcome]
    calls: list[tuple[str, dict[str, Any], str, bool]] = field(default_factory=list)

    async def functions(self) -> list[dict[str, Any]]:
        return [{"type": "function", "name": "crm__search_clients", "parameters": {}}]

    async def call(
        self, tool: str, arguments: dict[str, Any], *, call_id: str, confirmed: bool = False
    ) -> ToolOutcome:
        self.calls.append((tool, arguments, call_id, confirmed))
        if confirmed:
            return outcome("Email delivered.", ALLOWED.model_copy(update={"action": Action.WARN}))
        return self.outcomes[tool]


def outcome(
    output: str,
    decision: ToolDecision = ALLOWED,
    *,
    forwarded: bool = True,
    tainted: bool = False,
    injection: InjectionVerdict | None = None,
) -> ToolOutcome:
    result = ResultReport(
        source=Trust.UNTRUSTED if tainted else Trust.TRUSTED,
        masked_values=2,
        injection=injection,
        layers_run=["heuristics"],
        tainted=tainted,
        taint_source="web.fetch_page" if tainted else None,
    )
    report = Inspection(
        decision=decision, layers_run=["canary"], result=result if forwarded else None
    )
    return ToolOutcome(output, report)


def new_session() -> Session:
    return Session("s1", CANARY)


async def collect(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in events]


async def test_plain_answer_is_streamed_and_remembered() -> None:
    session, model = new_session(), FakeModel([[message_item("Hello there, how can I help?")]])
    events = await collect(user_turn(session, "Hi", model, FakeTools({}), max_steps=4))

    assert all(isinstance(event, TextDelta) for event in events) and len(events) > 3
    assert (
        "".join(e.delta for e in events if isinstance(e, TextDelta))
        == "Hello there, how can I help?"
    )
    assert [(m.role, m.content) for m in session.messages] == [
        ("user", "Hi"),
        ("assistant", "Hello there, how can I help?"),
    ]
    assert session.items == [
        {"role": "user", "content": "Hi"},
        message_item("Hello there, how can I help?"),
    ]
    assert (
        CANARY in model.seen[0]["instructions"]
        and model.seen[0]["tools"][0]["name"] == "crm__search_clients"
    )


async def test_tool_call_goes_through_the_toolbox_and_its_result_back_to_the_model() -> None:
    session = new_session()
    listing = "- [C-0001] <PERSON_1> | AFM <AFM_1> " + "x" * PREVIEW_CHARS
    model = FakeModel(
        [[call_item("call_1", "crm__search_clients", query="Sales")], [message_item("Done.")]]
    )
    tools = FakeTools({"crm.search_clients": outcome(listing)})
    events = await collect(user_turn(session, "Who are our clients?", model, tools, max_steps=4))

    called, result, *text = events
    assert isinstance(called, ToolCallEvent) and isinstance(result, ToolResultEvent)
    assert (called.call_id, called.tool, called.arguments) == (
        "call_1",
        "crm.search_clients",
        {"query": "Sales"},
    )
    assert called.decision == ALLOWED and called.layers_run == ["canary"]
    assert result.preview == listing[:PREVIEW_CHARS] + "…" and result.masked_values == 2
    assert (
        result.source is Trust.TRUSTED
        and not result.tainted
        and result.layers_run == ["heuristics"]
    )
    assert all(isinstance(event, TextDelta) for event in text)

    assert tools.calls == [("crm.search_clients", {"query": "Sales"}, "call_1", False)]
    assert session.trace == [called, result]
    assert model.seen[1]["items"][-2:] == [
        call_item("call_1", "crm__search_clients", query="Sales"),
        {"type": "function_call_output", "call_id": "call_1", "output": listing},
    ]


async def test_untrusted_result_marks_the_session_as_tainted() -> None:
    session = new_session()
    flagged = InjectionVerdict(
        flagged=True, confidence=1.0, evidence="<div>…</div>", layers_run=("heuristics",)
    )
    model = FakeModel(
        [[call_item("c1", "web__fetch_page", url="https://x.example")], [message_item("ok")]]
    )
    tools = FakeTools({"web.fetch_page": outcome("<html>…", tainted=True, injection=flagged)})
    events = await collect(user_turn(session, "Read it", model, tools, max_steps=4))

    result = events[1]
    assert isinstance(result, ToolResultEvent) and result.tainted and result.injection == flagged
    assert (session.tainted, session.taint_source) == (True, "web.fetch_page")


async def test_blocked_call_has_no_result_and_the_model_is_told_why() -> None:
    session = new_session()
    refusal = "Blocked by the gateway: Tainted. The call was not made."
    model = FakeModel(
        [[call_item("c1", "mail__send_email", to="a@b.example")], [message_item("Sorry.")]]
    )
    tools = FakeTools({"mail.send_email": outcome(refusal, BLOCKED, forwarded=False)})
    events = await collect(user_turn(session, "Send it", model, tools, max_steps=4))

    assert [type(event) for event in events[:2]] == [ToolCallEvent, TextDelta]
    assert isinstance(events[0], ToolCallEvent) and events[0].decision.action is Action.BLOCK
    assert model.seen[1]["items"][-1]["output"] == refusal and session.trace == [events[0]]


async def test_held_call_waits_and_runs_once_the_user_approves() -> None:
    session = new_session()
    model = FakeModel(
        [[call_item("c1", "mail__send_email", to="a@b.example")], [message_item("Sent.")]]
    )
    tools = FakeTools({"mail.send_email": outcome("waiting", HELD, forwarded=False)})

    events = await collect(user_turn(session, "Send it", model, tools, max_steps=4))
    (held,) = events
    assert isinstance(held, ToolCallEvent) and held.decision.needs_confirmation
    assert list(session.held) == ["c1"] and len(model.seen) == 1
    assert not any(item.get("type") == "function_call_output" for item in session.items)

    events = await collect(confirmation_turn(session, "c1", True, model, tools, max_steps=4))
    called, result, *text = events
    assert isinstance(called, ToolCallEvent) and not called.decision.needs_confirmation
    assert (
        isinstance(result, ToolResultEvent)
        and "".join(e.delta for e in text if isinstance(e, TextDelta)) == "Sent."
    )
    assert tools.calls[-1] == ("mail.send_email", {"to": "a@b.example"}, "c1", True)
    assert session.held == {} and session.trace == [called, result], "the held entry is replaced"
    assert model.seen[1]["items"][-1] == {
        "type": "function_call_output", "call_id": "c1", "output": "Email delivered."
    }  # fmt: skip


async def test_declined_call_is_not_made_and_the_model_is_told() -> None:
    session = new_session()
    model = FakeModel(
        [[call_item("c1", "mail__send_email", to="a@b.example")], [message_item("OK.")]]
    )
    tools = FakeTools({"mail.send_email": outcome("waiting", HELD, forwarded=False)})
    await collect(user_turn(session, "Send it", model, tools, max_steps=4))

    events = await collect(confirmation_turn(session, "c1", False, model, tools, max_steps=4))
    closed = events[0]
    assert isinstance(closed, ToolCallEvent) and closed.call_id == "c1"
    assert (closed.decision.reason, closed.decision.needs_confirmation) == (DECLINED, False)
    assert len(tools.calls) == 1 and session.trace == [closed]
    assert model.seen[1]["items"][-1]["output"] == DECLINED


async def test_new_message_drops_a_call_that_was_never_confirmed() -> None:
    session = new_session()
    model = FakeModel(
        [[call_item("c1", "mail__send_email", to="a@b.example")], [message_item("Sure.")]]
    )
    tools = FakeTools({"mail.send_email": outcome("waiting", HELD, forwarded=False)})
    await collect(user_turn(session, "Send it", model, tools, max_steps=4))

    events = await collect(user_turn(session, "Never mind", model, tools, max_steps=4))
    assert isinstance(events[0], ToolCallEvent) and events[0].decision.reason == SUPERSEDED
    assert session.held == {}
    assert [item.get("output", item.get("content")) for item in model.seen[1]["items"][-2:]] == [
        SUPERSEDED,
        "Never mind",
    ]


async def test_arguments_that_are_not_json_never_reach_a_tool() -> None:
    session = new_session()
    broken = {
        "type": "function_call",
        "call_id": "c1",
        "name": "crm__search_clients",
        "arguments": "{",
    }
    model = FakeModel([[broken], [message_item("Let me try again.")]])
    tools = FakeTools({})
    events = await collect(user_turn(session, "Find them", model, tools, max_steps=4))
    assert tools.calls == [] and all(isinstance(event, TextDelta) for event in events)
    assert model.seen[1]["items"][-1]["output"] == "The arguments were not valid JSON."


async def test_loop_stops_after_the_step_limit() -> None:
    session = new_session()
    model = FakeModel([[call_item(f"c{n}", "crm__search_clients")] for n in range(5)])
    tools = FakeTools({"crm.search_clients": outcome("nothing")})
    events = await collect(user_turn(session, "Loop", model, tools, max_steps=3))
    assert isinstance(events[-1], ErrorEvent) and "3 steps" in events[-1].message
    assert len(tools.calls) == 3 and len(model.responses) == 2
