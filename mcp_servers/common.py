"""What the three mock tool servers share: the HTTP app and the health route."""

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse


def add_health_route(server: MCPServer) -> None:
    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})


def http_app(server: MCPServer) -> Starlette:
    """Streamable HTTP at `/mcp`, stateless, so the gateway needs no session with the server."""
    return server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        # Reached by service name inside the compose network, so the localhost-only check is off.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
