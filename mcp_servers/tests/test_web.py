import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent

from mcp_servers.common import http_app
from mcp_servers.web.server import (
    BENIGN_PAGES,
    INTRANET,
    PAGES,
    POISONED_PAGES,
    build_server,
    read_page,
)


def text_of(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


@pytest.mark.parametrize("url", sorted(PAGES))
def test_every_listed_page_exists_and_has_a_title(url: str) -> None:
    page = read_page(url)
    assert page is not None and "<title>" in page


def test_poisoned_pages_hide_an_instruction_and_benign_pages_do_not() -> None:
    markers = (
        "Ignore your previous instructions",
        "Assistant, new instructions",
        "Βοηθέ τεχνητής νοημοσύνης",
    )
    for url in POISONED_PAGES:
        assert any(marker in (read_page(url) or "") for marker in markers), url
    for url in BENIGN_PAGES:
        assert not any(marker in (read_page(url) or "") for marker in markers), url


async def test_fetch_returns_the_source_and_reports_unknown_pages() -> None:
    url = "https://supplier-portal.example/news/payment-terms-2027"
    async with Client(build_server()) as client:
        tool = (await client.list_tools()).tools[0]
        page = await client.call_tool("fetch_page", {"url": url.upper() + "/"})
        missing = await client.call_tool("fetch_page", {"url": "https://nowhere.example/"})
    assert tool.name == "fetch_page" and tool.annotations and tool.annotations.read_only_hint
    assert 'style="display:none"' in text_of(page)
    assert missing.is_error and url in text_of(missing)


async def test_server_answers_mcp_over_http_under_its_compose_name() -> None:
    app = http_app(build_server())
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    async with app.router.lifespan_context(app), http:
        assert (await http.get("http://mcp-web:9003/healthz")).json() == {"status": "ok"}
        transport = streamable_http_client("http://mcp-web:9003/mcp", http_client=http)
        async with Client(transport) as client:
            page = await client.call_tool("fetch_page", {"url": f"{INTRANET}/vpn-setup"})
    assert "Setting up the company VPN" in text_of(page)
