"""The agent loop: ask the model, run the tool calls it asks for through the gateway, repeat
until it answers in words or the policy holds a call for the user to confirm."""

import json
from collections.abc import AsyncIterator
from typing import Any

from agent.model import Delta, Model
from agent.prompts import system_prompt
from agent.schemas import (
    AgentEvent,
    AgentMessage,
    ErrorEvent,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)
from agent.sessions import HeldCall, Session
from agent.tools import ToolBox, ToolOutcome, tool_name

PREVIEW_CHARS = 600
DECLINED = "The user declined this action. It was not carried out."
SUPERSEDED = "The user moved on without confirming this action. It was not carried out."


def _events_for(
    call_id: str, tool: str, arguments: dict[str, Any], outcome: ToolOutcome
) -> tuple[ToolCallEvent, ToolResultEvent | None]:
    report = outcome.inspection
    called = ToolCallEvent(
        call_id=call_id,
        tool=tool,
        arguments=arguments,
        decision=report.decision,
        layers_run=report.layers_run,
    )
    if report.result is None:
        return called, None
    preview = outcome.output[:PREVIEW_CHARS] + ("…" if len(outcome.output) > PREVIEW_CHARS else "")
    return called, ToolResultEvent(
        call_id=call_id,
        tool=tool,
        source=report.result.source,
        preview=preview,
        masked_values=report.result.masked_values,
        injection=report.result.injection,
        layers_run=report.result.layers_run,
        tainted=report.result.tainted,
    )


async def _run_call(
    session: Session,
    tools: ToolBox,
    call_id: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    confirmed: bool = False,
) -> AsyncIterator[AgentEvent]:
    """Send one call to the gateway and report what it decided and what came back."""
    outcome = await tools.call(tool, arguments, call_id=call_id, confirmed=confirmed)
    called, result = _events_for(call_id, tool, arguments, outcome)
    session.record(called)
    yield called
    if called.decision.needs_confirmation:
        session.held[call_id] = HeldCall(tool, arguments)
        return
    if result and outcome.inspection.result:
        session.tainted = result.tainted
        session.taint_source = outcome.inspection.result.taint_source
        session.record(result)
        yield result
    session.answer_call(call_id, outcome.output)


async def _advance(
    session: Session, model: Model, tools: ToolBox, max_steps: int
) -> AsyncIterator[AgentEvent]:
    functions = await tools.functions()
    instructions = system_prompt(session.canary)
    for _ in range(max_steps):
        text = ""
        output: list[dict[str, Any]] = []
        async for part in model.respond(
            instructions=instructions, items=session.items, tools=functions
        ):
            if isinstance(part, Delta):
                text += part.text
                yield TextDelta(delta=part.text)
            else:
                output = part.items
        session.items.extend(output)
        if text:
            session.messages.append(AgentMessage(role="assistant", content=text))
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            return
        for call in calls:
            try:
                arguments = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                session.answer_call(call["call_id"], "The arguments were not valid JSON.")
                continue
            tool = tool_name(call["name"])
            async for event in _run_call(session, tools, call["call_id"], tool, arguments):
                yield event
        if session.held:
            return
    yield ErrorEvent(message=f"The assistant stopped after {max_steps} steps without an answer.")


async def user_turn(
    session: Session, content: str, model: Model, tools: ToolBox, *, max_steps: int
) -> AsyncIterator[AgentEvent]:
    """Handle a new message from the user."""
    for call_id in list(session.held):
        yield session.drop_held(call_id, SUPERSEDED)
    session.items.append({"role": "user", "content": content})
    session.messages.append(AgentMessage(role="user", content=content))
    async for event in _advance(session, model, tools, max_steps):
        yield event


async def confirmation_turn(
    session: Session, call_id: str, approve: bool, model: Model, tools: ToolBox, *, max_steps: int
) -> AsyncIterator[AgentEvent]:
    """Carry out or drop a held call, then let the model continue once nothing is held."""
    if approve:
        held = session.held.pop(call_id)
        async for event in _run_call(
            session, tools, call_id, held.tool, held.arguments, confirmed=True
        ):
            yield event
    else:
        yield session.drop_held(call_id, DECLINED)
    if not session.held:
        async for event in _advance(session, model, tools, max_steps):
            yield event
