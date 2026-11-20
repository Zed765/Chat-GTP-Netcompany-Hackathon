"""Mock mail: send email, read the helpdesk inbox, and show what reached outside addresses."""

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp_servers.common import add_health_route, http_app
from mcp_servers.mail.mailbox import Mailbox, domain_of, parse_recipients

INTERNAL_DOMAIN = os.environ.get("ASPIDA_INTERNAL_MAIL_DOMAIN", "aspida-demo.example")


def build_server(mailbox: Mailbox | None = None) -> MCPServer:
    box = mailbox or Mailbox(internal_domain=INTERNAL_DOMAIN)
    server = MCPServer(
        "aspida-mail",
        instructions="The helpdesk mailbox of the demo organisation. Nothing leaves this server.",
    )
    add_health_route(server)

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=True
        ),
        structured_output=False,
    )
    def send_email(
        to: Annotated[str, Field(description="One address, or several separated by commas")],
        subject: Annotated[str, Field(max_length=300)],
        body: Annotated[str, Field(max_length=50_000)],
    ) -> str:
        """Send an email from the helpdesk assistant's address."""
        recipients = parse_recipients(to)
        if not recipients:
            raise ToolError("The email needs at least one recipient.")
        unreadable = [address for address in recipients if domain_of(address) is None]
        if unreadable:
            raise ToolError(
                f"This is not an email address: {', '.join(unreadable)}. Nothing was sent."
            )
        delivered = box.send(to, subject, body)
        return f"Email delivered to {', '.join(message.recipient for message in delivered)}."

    @server.tool(annotations=ToolAnnotations(read_only_hint=True), structured_output=False)
    def list_inbox(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> str:
        """List the newest messages in the helpdesk inbox: ID, sender, date and subject."""
        newest = sorted(box.inbox, key=lambda message: message.received, reverse=True)[:limit]
        if not newest:
            return "The inbox is empty."
        lines = [
            f"- [{m.id}] {m.received:%d %b %H:%M} | from {m.sender} | {m.subject}" for m in newest
        ]
        return "\n".join([f"{len(newest)} message(s) in the inbox:", *lines])

    @server.tool(annotations=ToolAnnotations(read_only_hint=True), structured_output=False)
    def read_email(
        message_id: Annotated[str, Field(description="The ID shown in brackets by list_inbox")],
    ) -> str:
        """Read one message from the helpdesk inbox in full."""
        wanted = message_id.strip().casefold()
        message = next((m for m in box.inbox if m.id == wanted), None)
        if message is None:
            raise ToolError("No message has that ID. Use list_inbox to see the inbox.")
        return (
            f"From: {message.sender}\nTo: {message.recipient}\n"
            f"Date: {message.received:%d %b %Y %H:%M}\nSubject: {message.subject}\n\n"
            f"{message.body}"
        )

    @server.custom_route("/attacker-inbox", methods=["GET"])
    async def attacker_inbox(_: Request) -> JSONResponse:
        return JSONResponse([message.as_json() for message in box.outside()])

    @server.custom_route("/attacker-inbox", methods=["DELETE"])
    async def clear_attacker_inbox(_: Request) -> Response:
        box.clear_outside()
        return Response(status_code=204)

    return server


app = http_app(build_server())
