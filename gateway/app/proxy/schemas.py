from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gateway.app.core.types import (
    Action,
    Explanation,
    RehydrationReport,
    RowSource,
    Store,
    Tier,
    ToolRef,
    Usage,
)

TOOL_HEADER = "X-Aspida-Tool"
CONVERSATION_HEADER = "X-Aspida-Conversation"
ACKNOWLEDGE_HEADER = "X-Aspida-Acknowledge-Warning"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    """An OpenAI Chat Completions request. Every field is read before anything is forwarded;
    one the gateway does not know is refused with a 400 that names it."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False


class ResponsesRequest(BaseModel):
    """An OpenAI Responses request. The gateway is stateless: send the whole `input` each
    time, without `previous_response_id`. A field the gateway does not know is refused with
    a 400 that names it."""

    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[dict[str, Any]]
    instructions: str | None = None
    stream: bool = False


class SpanView(BaseModel):
    """A finding in the last user message, in the coordinates of what the user typed.
    `placeholder` is null for a finding that is flagged but left in place, such as a
    confidentiality marker."""

    start: int
    end: int
    placeholder: str | None
    data_type: str
    tier: Tier
    recogniser: str
    encoded: bool
    store: Store | None
    source: RowSource | None
    match_label: str | None


class UpstreamMessage(BaseModel):
    role: str
    content: str


class Trace(BaseModel):
    """Sent with every proxied response as the `aspida` field. It is built for the caller and
    never stored, because `spans` describe the caller's own raw text."""

    trace_id: str
    conversation_id: str
    tool: ToolRef
    action: Action
    rule: str
    policy_version: int
    explanation: Explanation
    forwarded: bool
    needs_acknowledgement: bool = Field(
        description=f"True for an unconfirmed warn: resend with `{ACKNOWLEDGE_HEADER}: true`"
    )
    upstream_messages: list[UpstreamMessage] = Field(
        description="What the AI tool saw, or would see if a warning is acknowledged"
    )
    spans: list[SpanView]
    tiers_run: list[Tier]
    timings_ms: dict[str, float]


class TraceSummary(BaseModel):
    """Sent as `aspida_summary` once the response is complete."""

    trace_id: str
    rehydration: RehydrationReport
    usage: Usage
    latency_ms: float


class ChatCompletionEnvelope(BaseModel):
    """An OpenAI chat completion, or one streamed chunk of it, plus the `aspida` fields.

    When streaming, the first chunk carries `aspida` and the last one before `[DONE]` carries
    `aspida_summary`; both have empty `choices`. Otherwise both arrive in the one response.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: str
    model: str
    choices: list[dict[str, Any]]
    aspida: Trace | None = None
    aspida_summary: TraceSummary | None = None


class PolicyError(BaseModel):
    message: str
    type: Literal["aspida_policy_block", "aspida_policy_warning"]
    code: str


class PolicyErrorResponse(BaseModel):
    """Body of the 403 (block) and 409 (warn) answers, shaped like an OpenAI error."""

    error: PolicyError
    aspida: Trace


class PromptRecord(BaseModel):
    """One prompt from an activity log, for example an export from a browser plug-in."""

    ts: datetime
    user_id: str
    tool: str = Field(description="Inventory slug or domain of the AI tool it was sent to")
    text: str = Field(min_length=1, max_length=50_000)
    enforced: bool = Field(
        default=False,
        description=(
            "False: the prompt was only observed, so it reached the tool as written. "
            "True: record it as if the gateway had been in the path and applied the policy"
        ),
    )


class IngestResult(BaseModel):
    ingested: int
    actions: dict[Action, int] = Field(description="What the active policy would have done")


class Example(BaseModel):
    id: str
    page: Literal["chat"]
    language: Literal["en", "el"]
    title: str
    prompt: str
    tool: str | None = None
    expected: Action | None = None
    note: str | None = None
