import json
from pathlib import Path

import httpx2
from mcp import Client
from mcp_types import CallToolResult, TextContent

from mcp_servers.common import http_app
from mcp_servers.crm.clients import FIXTURE, ClientDirectory
from mcp_servers.crm.server import build_server


def text_of(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def test_tools_declare_whether_they_change_anything() -> None:
    async with Client(build_server(ClientDirectory(FIXTURE))) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == {"search_clients", "get_client", "add_note"}
    read_only = {
        name: tool.annotations and tool.annotations.read_only_hint for name, tool in tools.items()
    }
    assert read_only == {"search_clients": True, "get_client": True, "add_note": False}


async def test_search_ignores_case_and_accents_and_finds_by_team() -> None:
    async with Client(build_server(ClientDirectory(FIXTURE))) as client:
        by_name = text_of(await client.call_tool("search_clients", {"query": "ηλιος ναυτιλιακη"}))
        by_team = text_of(await client.call_tool("search_clients", {"query": "Sales team"}))
        nothing = text_of(await client.call_tool("search_clients", {"query": "zzz"}))
    assert "[C-0001]" in by_name and "1 client(s) found" in by_name
    assert {"[C-0001]", "[C-0002]", "[C-0006]"} <= set(
        by_team.split()
    ) and "[C-0003]" not in by_team
    assert nothing == "No client matches that search."


async def test_a_long_list_comes_in_pages_and_says_how_to_read_on() -> None:
    async with Client(build_server(ClientDirectory(FIXTURE))) as client:
        first = text_of(await client.call_tool("search_clients", {"limit": 2}))
        last = text_of(await client.call_tool("search_clients", {"limit": 4, "offset": 2}))
        beyond = text_of(await client.call_tool("search_clients", {"offset": 6}))
        everything = text_of(await client.call_tool("search_clients", {}))
    assert first.startswith("6 client(s) found, showing 1 to 2. Call again with offset=2")
    assert first.count("\n- ") == 2
    assert last.startswith("6 client(s) found, showing 3 to 6, the last ones:")
    assert last.count("\n- ") == 4 and not set(first.splitlines()[1:]) & set(last.splitlines()[1:])
    assert beyond == "6 client(s) found, and none after the first 6."
    assert everything.startswith("6 client(s) found:")


async def test_note_is_added_and_shown_on_the_record() -> None:
    async with Client(build_server(ClientDirectory(FIXTURE))) as client:
        added = await client.call_tool("add_note", {"client_id": "c-0002", "note": "Call back"})
        record = text_of(await client.call_tool("get_client", {"client_id": "C-0002"}))
        missing = await client.call_tool("get_client", {"client_id": "C-9999"})
    assert not added.is_error and "[C-0002]" in text_of(added)
    assert "IBAN: GR7729132158252742264232026" in record and "Note: Call back" in record
    assert missing.is_error and "No client has that ID" in text_of(missing)


async def test_export_returns_the_client_file_as_it_is() -> None:
    app = http_app(build_server(ClientDirectory(FIXTURE)))
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http:
        response = await http.get("http://crm/export/clients")
    assert response.status_code == 200 and response.json() == FIXTURE


def test_seeded_file_is_preferred_and_read_leniently(tmp_path: Path) -> None:
    seeded = tmp_path / "clients.json"
    seeded.write_text(
        json.dumps([{"id": 7, "legal_name": "Δοκιμή ΑΕ", "trade_name": None, "team": "Legal"}]),
        encoding="utf-8",
    )
    directory = ClientDirectory.load(seeded)
    assert [client.id for client in directory.search("δοκιμη")] == ["7"]
    assert len(ClientDirectory.load(tmp_path / "missing.json").clients) == len(FIXTURE)
