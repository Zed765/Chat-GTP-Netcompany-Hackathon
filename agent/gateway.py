"""The agent's only way out: the gateway. Its model calls, its tool calls and its session
state all go there, each carrying the signed-in user's token and the session ID."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI
from pydantic import BaseModel

from agent.config import Settings
from agent.tools import GatewayTools
from gateway.app.core.types import InjectionProtection

CONVERSATION_HEADER = "X-Aspida-Conversation"
TOOL_HEADER = "X-Aspida-Tool"
AI_TOOL = "company-assistant"


class GatewaySession(BaseModel):
    """What the gateway holds about an agent session."""

    session_id: str
    protection: InjectionProtection
    tainted: bool
    taint_source: str | None
    live_model: str
    canary: str | None = None


class Gateway:
    def __init__(
        self, settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._url = settings.gateway_url.rstrip("/")
        self._timeout = settings.request_timeout_s
        self._transport = transport

    def _http(self, token: str, session_id: str | None = None) -> httpx2.AsyncClient:
        headers = {"Authorization": f"Bearer {token}", TOOL_HEADER: AI_TOOL}
        if session_id:
            headers[CONVERSATION_HEADER] = session_id
        return httpx2.AsyncClient(
            base_url=self._url, headers=headers, timeout=self._timeout, transport=self._transport
        )

    async def start_session(self, token: str) -> GatewaySession:
        """Raises `httpx2.HTTPStatusError` with 401 if the token is not a valid sign-in."""
        async with self._http(token) as http:
            response = await http.post("/api/agent/sessions")
        return GatewaySession.model_validate(response.raise_for_status().json())

    async def session(self, token: str, session_id: str) -> GatewaySession:
        """Raises `httpx2.HTTPStatusError` with 404 if the session is not this user's."""
        async with self._http(token) as http:
            response = await http.get(f"/api/agent/sessions/{session_id}")
        return GatewaySession.model_validate(response.raise_for_status().json())

    async def end_session(self, token: str, session_id: str) -> None:
        async with self._http(token) as http:
            response = await http.delete(f"/api/agent/sessions/{session_id}")
        response.raise_for_status()

    def model_client(self, token: str, session_id: str) -> AsyncOpenAI:
        """An OpenAI client pointed at the gateway. A refused request is not tried again."""
        return AsyncOpenAI(
            api_key=token,
            base_url=f"{self._url}/v1",
            http_client=self._http(token, session_id),
            max_retries=0,
        )

    @asynccontextmanager
    async def tools(self, token: str, session_id: str) -> AsyncIterator[GatewayTools]:
        async with self._http(token, session_id) as http:
            endpoint = streamable_http_client(f"{self._url}/mcp", http_client=http)
            async with Client(endpoint) as client:
                yield GatewayTools(client)
