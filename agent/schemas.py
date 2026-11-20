"""The agent service API, as the Agent page consumes it."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from gateway.app.core.types import Action, InjectionProtection, InjectionVerdict, Trust


class ToolDecision(BaseModel):
    """What the gateway decided about one outgoing tool call."""

    action: Action
    rule: str
    reason: str
    resolved: bool = Field(description="True if the tool received real values, not placeholders")
    needs_confirmation: bool = False


class TextDelta(BaseModel):
    type: Literal["text"] = "text"
    delta: str


class ToolCallEvent(BaseModel):
    """A call with a `call_id` seen before replaces the earlier one: it is the same call,
    decided again after the user confirmed or declined it."""

    type: Literal["tool_call"] = "tool_call"
    call_id: str
    tool: str = Field(description="`<server>.<tool>`, for example `mail.send_email`")
    arguments: dict[str, Any] = Field(description="As the model wrote them, placeholders included")
    decision: ToolDecision
    layers_run: list[str] = Field(default_factory=list)


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    tool: str
    source: Trust
    preview: str = Field(description="The masked result as the model saw it, shortened")
    masked_values: int
    injection: InjectionVerdict | None
    layers_run: list[str] = Field(default_factory=list)
    tainted: bool


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    tainted: bool
    taint_source: str | None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


AgentEvent = Annotated[
    TextDelta | ToolCallEvent | ToolResultEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]
TraceStep = Annotated[ToolCallEvent | ToolResultEvent, Field(discriminator="type")]


class AgentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentSession(BaseModel):
    session_id: str
    protection: InjectionProtection
    tainted: bool
    taint_source: str | None
    messages: list[AgentMessage]
    trace: list[TraceStep]
    request_of_call: dict[str, int] = Field(
        description="For each call in the trace, the request it followed: its place, from 0, "
        "among the user's messages"
    )


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class ConfirmIn(BaseModel):
    approve: bool
