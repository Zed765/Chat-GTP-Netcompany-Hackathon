"""The gateway as an MCP server: one streamable HTTP endpoint that lists the tools of the
servers behind it as `<server>.<tool>` and sends every call through the broker."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, cast

import httpx2
import jwt
import mcp_types as types
from fastapi import Depends, FastAPI, Request
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import MCPError
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from gateway.app.core.auth import read_token
from gateway.app.core.services import Services
from gateway.app.mcp_proxy.broker import Caller, ToolBroker
from gateway.app.mcp_proxy.schemas import (
    CALL_ID_META_KEY,
    CONFIRMED_META_KEY,
    INSPECTION_META_KEY,
)
from gateway.app.mcp_proxy.sessions import AgentSessions
from gateway.app.mcp_proxy.upstream import CALL_TIMEOUT_S, ToolServers, server_urls

CONVERSATION_HEADER = "X-Aspida-Conversation"
TOOL_HEADER = "X-Aspida-Tool"
DEFAULT_AI_TOOL = "company-assistant"
CALLER_SCOPE_KEY = "aspida.caller"


@dataclass(frozen=True)
class AgentProxy:
    """Built once when the gateway starts; routes reach it through `Proxy`."""

    sessions: AgentSessions
    broker: ToolBroker
    transport: StreamableHTTPSessionManager
    http: httpx2.AsyncClient


def build_mcp_server(broker: ToolBroker) -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        catalogue = await broker.servers.catalogue()
        return types.ListToolsResult(tools=[tool.advertised() for tool in catalogue.values()])

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        if ctx.request is None:
            raise MCPError(types.INVALID_REQUEST, "Tool calls are only served over HTTP")
        meta = ctx.meta or {}
        call_id = meta.get(CALL_ID_META_KEY)
        outcome = await broker.call(
            cast(Caller, ctx.request.scope[CALLER_SCOPE_KEY]),
            params.name,
            params.arguments or {},
            call_id=call_id if isinstance(call_id, str) else None,
            confirmed=meta.get(CONFIRMED_META_KEY) is True,
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=outcome.text)],
            is_error=outcome.is_error,
            _meta={INSPECTION_META_KEY: outcome.inspection.model_dump(mode="json")},
        )

    return Server(
        "aspida-gateway",
        instructions="Tools of the organisation, behind the A.S.P.I.D.A. gateway's policy.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        get_tool_input_schema=broker.servers.input_schema,
    )


def tool_http_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(timeout=httpx2.Timeout(CALL_TIMEOUT_S))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs inside the gateway's own lifespan, so the services are already built."""
    services: Services = app.state.services
    sessions = AgentSessions(services.redis, services.settings.vault_ttl_hours * 3600)
    async with tool_http_client() as http:
        broker = ToolBroker(services, ToolServers(server_urls(services.settings), http), sessions)
        transport = StreamableHTTPSessionManager(
            app=build_mcp_server(broker), json_response=True, stateless=True
        )
        async with transport.run():
            app.state.agent_proxy = AgentProxy(sessions, broker, transport, http)
            yield


def get_proxy(request: Request) -> AgentProxy:
    return cast(AgentProxy, request.app.state.agent_proxy)


Proxy = Annotated[AgentProxy, Depends(get_proxy)]


async def authenticate(request: Request, proxy: AgentProxy) -> Caller | None:
    """The signed-in user and their agent session, or `None` if either is missing."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.casefold() != "bearer":
        return None
    services: Services = request.app.state.services
    try:
        principal = read_token(token, services.keys.session)
    except jwt.PyJWTError:
        return None
    session_id = request.headers.get(CONVERSATION_HEADER, "")
    state = await proxy.sessions.get(session_id) if session_id else None
    if state is None or state.owner != principal.user_id:
        return None
    # The header is the caller's own text and every event records it, so it only counts
    # when it is the slug of a tool in the inventory.
    named = request.headers.get(TOOL_HEADER)
    known = {tool.slug for tool in services.inventory.tools()}
    return Caller(principal, session_id, named if named in known else DEFAULT_AI_TOOL)


class McpEndpoint:
    """`/mcp` as an ASGI app: authenticates the agent, then hands over to the MCP transport."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        proxy = get_proxy(request)
        caller = await authenticate(request, proxy)
        if caller is None:
            detail = f"Sign in, and send the ID of your agent session in {CONVERSATION_HEADER}"
            await JSONResponse({"detail": detail}, status_code=401)(scope, receive, send)
            return
        scope[CALLER_SCOPE_KEY] = caller
        await proxy.transport.handle_request(scope, receive, send)
