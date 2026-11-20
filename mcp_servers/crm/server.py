"""Mock CRM: search and read client records, add a note, and export the client list."""

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_servers.common import add_health_route, http_app
from mcp_servers.crm.clients import ClientDirectory, ClientRecord

MAX_RESULTS = 25
UNKNOWN_CLIENT = "No client has that ID. Use search_clients to find the right one."


def _summary_line(client: ClientRecord) -> str:
    contact = client.contacts[0] if client.contacts else None
    fields = [
        f"[{client.id}] {client.display_name}",
        client.kind,
        f"AFM {client.afm}" if client.afm else None,
        client.email,
        client.phone,
        f"contact: {contact.name}" if contact else None,
        f"team {client.team}" if client.team else None,
    ]
    return "- " + " | ".join(part for part in fields if part)


def _full_record(client: ClientRecord, notes: list[str]) -> str:
    lines = [
        f"[{client.id}] {client.display_name}",
        f"Kind: {client.kind}",
        f"AFM: {client.afm}",
        f"IBAN: {client.iban}",
        f"Email: {client.email}",
        f"Phone: {client.phone}",
        f"Address: {client.address}",
        f"Owning team: {client.team}",
    ]
    if client.aliases:
        lines.append(f"Also known as: {', '.join(client.aliases)}")
    for contact in client.contacts:
        details = ", ".join(part for part in (contact.role, contact.email, contact.phone) if part)
        lines.append(
            f"Contact: {contact.name} ({details})" if details else f"Contact: {contact.name}"
        )
    lines.extend(f"Note: {note}" for note in notes)
    return "\n".join(lines)


def build_server(directory: ClientDirectory | None = None) -> MCPServer:
    clients = directory or ClientDirectory.load()
    server = MCPServer(
        "aspida-crm",
        instructions="Client records of the demo organisation. Every value is invented.",
    )
    add_health_route(server)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True), structured_output=False)
    def search_clients(
        query: Annotated[
            str,
            Field(description="Name, alias, AFM, contact person or owning team. Empty lists all."),
        ] = "",
        limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 10,
        offset: Annotated[
            int, Field(ge=0, description="How many matches to skip, to read the next page")
        ] = 0,
    ) -> str:
        """Search the CRM. Returns one line per client with its ID and main contact details.
        A long list comes in pages: call again with `offset` to read on."""
        found = clients.search(query)
        if not found:
            return "No client matches that search."
        shown = found[offset : offset + limit]
        last = offset + len(shown)
        if not shown:
            return f"{len(found)} client(s) found, and none after the first {len(found)}."
        if len(shown) == len(found):
            header = f"{len(found)} client(s) found:"
        elif last < len(found):
            header = (
                f"{len(found)} client(s) found, showing {offset + 1} to {last}. "
                f"Call again with offset={last} for the next ones:"
            )
        else:
            header = f"{len(found)} client(s) found, showing {offset + 1} to {last}, the last ones:"
        return "\n".join([header, *(_summary_line(client) for client in shown)])

    @server.tool(annotations=ToolAnnotations(read_only_hint=True), structured_output=False)
    def get_client(
        client_id: Annotated[str, Field(description="The ID shown in brackets by search_clients")],
    ) -> str:
        """Read one client's full record: identifiers, bank account, address, contacts, notes."""
        client = clients.get(client_id)
        if client is None:
            raise ToolError(UNKNOWN_CLIENT)
        return _full_record(client, clients.notes.get(client.id, []))

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
        structured_output=False,
    )
    def add_note(
        client_id: Annotated[str, Field(description="The ID shown in brackets by search_clients")],
        note: Annotated[str, Field(min_length=1, max_length=2000)],
    ) -> str:
        """Add a note to a client's record."""
        client = clients.add_note(client_id, note)
        if client is None:
            raise ToolError(UNKNOWN_CLIENT)
        return f"Note added to [{client.id}] {client.display_name}."

    @server.custom_route("/export/clients", methods=["GET"])
    async def export_clients(_: Request) -> JSONResponse:
        return JSONResponse(clients.raw)

    return server


app = http_app(build_server())
