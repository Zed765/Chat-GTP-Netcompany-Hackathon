"""Agent sessions, kept in memory: the conversation as the user sees it, the same
conversation as Responses API input, and the tool-call trace."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agent.schemas import AgentMessage, ToolCallEvent, TraceStep


@dataclass(frozen=True)
class HeldCall:
    """A call the policy held: it runs only if the user confirms it."""

    tool: str
    arguments: dict[str, Any]


@dataclass
class Session:
    session_id: str
    canary: str
    tainted: bool = False
    taint_source: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    # For each tool call, which of the user's requests it followed, counting from 0. A page
    # that opens the session again uses it to put each call back under its request.
    request_of_call: dict[str, int] = field(default_factory=dict)
    held: dict[str, HeldCall] = field(default_factory=dict)
    busy: asyncio.Lock = field(default_factory=asyncio.Lock)

    def record(self, step: TraceStep) -> None:
        """Add a step to the trace. A call decided again takes the place of its first entry."""
        asked = sum(message.role == "user" for message in self.messages)
        self.request_of_call.setdefault(step.call_id, max(0, asked - 1))
        if isinstance(step, ToolCallEvent):
            for index, earlier in enumerate(self.trace):
                if isinstance(earlier, ToolCallEvent) and earlier.call_id == step.call_id:
                    self.trace[index] = step
                    return
        self.trace.append(step)

    def answer_call(self, call_id: str, output: str) -> None:
        self.items.append({"type": "function_call_output", "call_id": call_id, "output": output})

    def drop_held(self, call_id: str, reason: str) -> ToolCallEvent:
        """Close a held call that will not run: tell the model, and say why in the trace."""
        del self.held[call_id]
        self.answer_call(call_id, reason)
        shown = next(
            step
            for step in self.trace
            if isinstance(step, ToolCallEvent) and step.call_id == call_id
        )
        decision = shown.decision.model_copy(update={"reason": reason, "needs_confirmation": False})
        closed = shown.model_copy(update={"decision": decision})
        self.record(closed)
        return closed


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
