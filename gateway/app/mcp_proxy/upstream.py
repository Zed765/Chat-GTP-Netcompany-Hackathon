"""The gateway as an MCP client: lists and calls the tools of the servers behind it."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx2
import mcp_types as types
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from gateway.app.config import Settings

log = logging.getLogger(__name__)

CATALOGUE_SECONDS = 30.0
CALL_TIMEOUT_S = 20.0
MAX_PAGES = 20
# The organisation's own mail system. It is not trusted by default, because what it retrieves
# (inbound mail) is untrusted; what it delivers is judged by its recipients.
MAIL_SERVER = "mail"


def server_urls(settings: Settings) -> dict[str, str]:
    return {"crm": settings.crm_url, MAIL_SERVER: settings.mail_url, "web": settings.web_tool_url}


@dataclass(frozen=True)
class ProxiedTool:
    server: str
    definition: types.Tool

    @property
    def name(self) -> str:
        """The name the agent sees: `<server>.<tool>`."""
        return f"{self.server}.{self.definition.name}"

    @property
    def side_effects(self) -> bool:
        """True unless the server declares the tool read-only."""
        annotations = self.definition.annotations
        return not (annotations and annotations.read_only_hint)

    @property
    def parameters(self) -> frozenset[str]:
        """The names of the arguments the tool's input schema declares."""
        properties = self.definition.input_schema.get("properties")
        return frozenset(properties) if isinstance(properties, dict) else frozenset()

    def advertised(self) -> types.Tool:
        # No output schema: the gateway returns inspected text, never the raw structured result.
        return types.Tool(
            name=self.name,
            title=self.definition.title,
            description=self.definition.description,
            input_schema=self.definition.input_schema,
            annotations=self.definition.annotations,
        )


class ToolServers:
    """Connects per operation: the servers are stateless, so one that restarts needs no care."""

    def __init__(self, urls: Mapping[str, str], http: httpx2.AsyncClient) -> None:
        self._urls = dict(urls)
        self._http = http
        self._catalogue: dict[str, ProxiedTool] = {}
        self._fresh_until = 0.0

    def _connect(self, server: str) -> Client:
        transport = streamable_http_client(f"{self._urls[server]}/mcp", http_client=self._http)
        return Client(transport, read_timeout_seconds=CALL_TIMEOUT_S, cache=None)

    async def _list(self, server: str) -> list[types.Tool]:
        tools: list[types.Tool] = []
        cursor: str | None = None
        async with self._connect(server) as client:
            for _ in range(MAX_PAGES):
                page = await client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if cursor is None:
                    break
        return tools

    async def catalogue(self) -> dict[str, ProxiedTool]:
        """Every reachable server's tools by proxied name, cached for a short while."""
        if monotonic() < self._fresh_until:
            return self._catalogue
        catalogue: dict[str, ProxiedTool] = {}
        complete = True
        for server in self._urls:
            try:
                listed = await self._list(server)
            except Exception as exc:
                log.warning("tool server %s did not list its tools: %s", server, type(exc).__name__)
                complete = False
                continue
            for definition in listed:
                tool = ProxiedTool(server, definition)
                catalogue[tool.name] = tool
        self._catalogue = catalogue
        # A server that was down is asked again on the next listing.
        self._fresh_until = monotonic() + CATALOGUE_SECONDS if complete else 0.0
        return catalogue

    def input_schema(self, name: str) -> Mapping[str, Any] | None:
        tool = self._catalogue.get(name)
        return None if tool is None else tool.definition.input_schema

    async def call(self, tool: ProxiedTool, arguments: dict[str, Any]) -> types.CallToolResult:
        async with self._connect(tool.server) as client:
            return await client.call_tool(tool.definition.name, arguments)
