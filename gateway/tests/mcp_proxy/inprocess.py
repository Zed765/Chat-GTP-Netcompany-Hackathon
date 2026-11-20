"""The gateway's agent routes and the three tool servers, wired together in one process."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult

from gateway.app.core.services import Services
from gateway.app.core.types import Principal
from gateway.app.mcp_proxy import server
from gateway.app.mcp_proxy.router import MCP_PATH, router
from gateway.app.mcp_proxy.schemas import INSPECTION_META_KEY, ToolInspection
from gateway.tests.mcp_proxy.fakes import EMPLOYEE, bearer
from mcp_servers.common import http_app
from mcp_servers.crm.clients import FIXTURE, ClientDirectory
from mcp_servers.crm.server import build_server as build_crm
from mcp_servers.mail.mailbox import Mailbox
from mcp_servers.mail.server import build_server as build_mail
from mcp_servers.web.server import build_server as build_web

GATEWAY_URL = "http://gateway:8000"


@dataclass
class Gateway:
    app: FastAPI
    http: httpx2.AsyncClient
    mailbox: Mailbox

    async def new_session(self, principal: Principal = EMPLOYEE) -> str:
        response = await self.http.post("/api/agent/sessions", headers=bearer(principal))
        session_id: str = response.raise_for_status().json()["session_id"]
        return session_id

    @asynccontextmanager
    async def tools(
        self, session_id: str, principal: Principal = EMPLOYEE, *, ai_tool: str | None = None
    ) -> AsyncIterator[Client]:
        """An MCP client connected the way the agent connects. `ai_tool` is what it sends in
        `X-Aspida-Tool`."""
        headers = bearer(principal) | {"X-Aspida-Conversation": session_id}
        if ai_tool is not None:
            headers["X-Aspida-Tool"] = ai_tool
        transport = httpx2.ASGITransport(app=self.app)
        async with httpx2.AsyncClient(transport=transport, headers=headers) as http:
            endpoint = streamable_http_client(f"{GATEWAY_URL}{MCP_PATH}", http_client=http)
            async with Client(endpoint) as client:
                yield client


def inspection_of(result: CallToolResult) -> ToolInspection:
    assert result.meta is not None
    return ToolInspection.model_validate(result.meta[INSPECTION_META_KEY])


@asynccontextmanager
async def running_gateway(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Gateway]:
    mailbox = Mailbox("aspida-demo.example")
    tool_apps = {
        "mcp-crm": http_app(build_crm(ClientDirectory(FIXTURE))),
        "mcp-mail": http_app(build_mail(mailbox)),
        "mcp-web": http_app(build_web()),
    }
    mounts = {f"all://{host}": httpx2.ASGITransport(app=app) for host, app in tool_apps.items()}
    monkeypatch.setattr(server, "tool_http_client", lambda: httpx2.AsyncClient(mounts=mounts))

    @asynccontextmanager
    async def with_services(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        yield

    app = FastAPI(lifespan=with_services)
    app.include_router(router)
    async with AsyncExitStack() as stack:
        for tool_app in tool_apps.values():
            await stack.enter_async_context(tool_app.router.lifespan_context(tool_app))
        await stack.enter_async_context(app.router.lifespan_context(app))
        http = await stack.enter_async_context(
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=GATEWAY_URL)
        )
        yield Gateway(app, http, mailbox)
