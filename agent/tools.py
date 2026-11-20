"""The agent's tools: everything the gateway's MCP endpoint lists, offered to the model as
function tools. Each result comes back with the gateway's inspection report attached."""

from dataclasses import dataclass
from typing import Any, Protocol, cast

from mcp import Client
from mcp_types import RequestParamsMeta, TextContent
from pydantic import BaseModel

from agent.schemas import ToolDecision
from gateway.app.core.types import InjectionVerdict, Trust

# Keys of the MCP `_meta` object, agreed with the gateway's proxy.
CALL_ID_META_KEY = "aspida/call_id"
CONFIRMED_META_KEY = "aspida/confirmed"
INSPECTION_META_KEY = "aspida/inspection"

# Function names may not contain a dot, so `crm.search_clients` is offered as
# `crm__search_clients`.
_SEPARATOR, _FUNCTION_SEPARATOR = ".", "__"


class ResultReport(BaseModel):
    source: Trust
    masked_values: int
    injection: InjectionVerdict | None
    layers_run: list[str]
    tainted: bool
    taint_source: str | None


class Inspection(BaseModel):
    """What the gateway decided about a call and found in its result."""

    decision: ToolDecision
    layers_run: list[str]
    result: ResultReport | None


@dataclass(frozen=True)
class ToolOutcome:
    output: str
    inspection: Inspection


class ToolBox(Protocol):
    async def functions(self) -> list[dict[str, Any]]:
        """The tools as Responses API function tools."""
        ...

    async def call(
        self, tool: str, arguments: dict[str, Any], *, call_id: str, confirmed: bool = False
    ) -> ToolOutcome:
        """Call `<server>.<tool>`. `confirmed` resends a call the user approved."""
        ...


def function_name(tool: str) -> str:
    return tool.replace(_SEPARATOR, _FUNCTION_SEPARATOR, 1)


def tool_name(function: str) -> str:
    return function.replace(_FUNCTION_SEPARATOR, _SEPARATOR, 1)


class GatewayTools:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def functions(self) -> list[dict[str, Any]]:
        listed = await self._client.list_tools()
        return [
            {
                "type": "function",
                "name": function_name(tool.name),
                "description": tool.description or "",
                "parameters": tool.input_schema,
                # MCP schemas have optional arguments, which strict mode does not allow.
                "strict": False,
            }
            for tool in listed.tools
        ]

    async def call(
        self, tool: str, arguments: dict[str, Any], *, call_id: str, confirmed: bool = False
    ) -> ToolOutcome:
        meta = {CALL_ID_META_KEY: call_id, CONFIRMED_META_KEY: confirmed}
        result = await self._client.call_tool(tool, arguments, meta=cast(RequestParamsMeta, meta))
        output = "\n".join(b.text for b in result.content if isinstance(b, TextContent))
        report = (result.meta or {}).get(INSPECTION_META_KEY)
        return ToolOutcome(output, Inspection.model_validate(report))
