"""Mock web: fetches a handful of local pages. Three of them carry a hidden instruction."""

from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from mcp_servers.common import add_health_route, http_app

PAGES_DIR = Path(__file__).parent / "pages"
INTRANET = "https://intranet.aspida-demo.example/kb"
SUPPLIER = "https://supplier-portal.example/news"

BENIGN_PAGES = {
    f"{INTRANET}/expenses-policy": "expenses-policy.html",
    f"{INTRANET}/prostasia-dedomenon": "prostasia-dedomenon.html",
    f"{INTRANET}/vpn-setup": "vpn-setup.html",
}
# Each hides an instruction addressed to an AI assistant that reads the page.
POISONED_PAGES = {
    f"{SUPPLIER}/payment-terms-2027": "payment-terms-2027.html",
    f"{SUPPLIER}/oroi-pliromis-2027": "oroi-pliromis-2027.html",
    f"{SUPPLIER}/security-questionnaire": "security-questionnaire.html",
}
PAGES = BENIGN_PAGES | POISONED_PAGES


def _normalise(url: str) -> str:
    return url.strip().rstrip("/").casefold()


def read_page(url: str) -> str | None:
    """The page's HTML source, comments and hidden elements included, as a scraper sees it."""
    filename = PAGES.get(_normalise(url))
    return None if filename is None else (PAGES_DIR / filename).read_text(encoding="utf-8")


def build_server() -> MCPServer:
    server = MCPServer(
        "aspida-web",
        instructions="Fetches web pages. Only a few local demo pages exist.",
    )
    add_health_route(server)

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
        structured_output=False,
    )
    def fetch_page(
        url: Annotated[str, Field(description="The full address, starting with https://")],
    ) -> str:
        """Fetch a web page and return its HTML source."""
        page = read_page(url)
        if page is None:
            raise ToolError("That page could not be fetched. Available pages: " + ", ".join(PAGES))
        return page

    return server


app = http_app(build_server())
