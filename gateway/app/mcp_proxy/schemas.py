from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from gateway.app.core.types import Action, InjectionProtection, InjectionVerdict, Trust

# Keys of the `_meta` object on an MCP `tools/call` request and on its result.
CALL_ID_META_KEY = "aspida/call_id"
CONFIRMED_META_KEY = "aspida/confirmed"
INSPECTION_META_KEY = "aspida/inspection"


class InboxMessage(BaseModel):
    id: str
    received: datetime
    sender: str
    recipient: str
    subject: str
    body: str


class AgentSessionOut(BaseModel):
    session_id: str
    protection: InjectionProtection
    tainted: bool
    taint_source: str | None = Field(description="The tool whose result tainted the session")
    live_model: str = Field(description="The model ID the agent asks for")


class AgentSessionCreated(AgentSessionOut):
    canary: str = Field(description="Goes into the agent's system prompt; shown only once")


class SeenRequest(BaseModel):
    texts: list[Annotated[str, StringConstraints(max_length=200_000)]] = Field(max_length=400)


class SeenResult(BaseModel):
    texts: list[str] = Field(description="The same texts, in order, as the agent's model saw them")


class AgentTool(BaseModel):
    name: str
    description: str | None
    side_effects: bool = Field(description="False only for a tool its system declares read-only")


class AgentSystem(BaseModel):
    """One system the agent reaches through the gateway, with the tools it offers."""

    server: str
    trusted: bool = Field(
        description="What it returns is believed, and real values may be sent to it"
    )
    tools: list[AgentTool]


class AgentTrustOut(BaseModel):
    systems: list[AgentSystem]
    mail_domains: list[str] = Field(
        description="Mail whose recipients are all on these domains carries real values"
    )


MailDomain = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=253,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$",
    ),
]


class AgentTrustUpdate(BaseModel):
    trusted_servers: list[str] = Field(max_length=20)
    mail_domains: list[MailDomain] = Field(max_length=50)


class CallDecision(BaseModel):
    """What the gateway decided about one outgoing tool call."""

    action: Action
    rule: str
    reason: str
    resolved: bool = Field(description="True if the tool received real values, not placeholders")
    needs_confirmation: bool = False


class ResultInspection(BaseModel):
    """What the gateway found in the tool's result before the model saw it."""

    source: Trust
    masked_values: int
    injection: InjectionVerdict | None = Field(description="`None` when protection is off")
    layers_run: list[str]
    tainted: bool
    taint_source: str | None


class ToolInspection(BaseModel):
    """Travels with every proxied tool result as `_meta["aspida/inspection"]`."""

    call_id: str
    tool: str
    decision: CallDecision
    layers_run: list[str] = Field(description="Checks run on the outgoing call")
    result: ResultInspection | None = Field(description="`None` if the call was not forwarded")
