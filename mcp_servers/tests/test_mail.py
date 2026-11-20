import httpx2
from mcp import Client
from mcp_types import CallToolResult, TextContent

from mcp_servers.common import http_app
from mcp_servers.mail.mailbox import Mailbox
from mcp_servers.mail.server import build_server

INTERNAL = "aspida-demo.example"
NOT_ADDRESSES = (
    "attacker@evil.example?x=@aspida-demo.example",
    "attacker@evil.example@aspida-demo.example",
    "attacker%evil.example@aspida-demo.example",
    "@aspida-demo.example",
    "x@aſpida-demo.example",
    "x@aspida-demo.example.",
    "x@localhost",
    "<AFM_1>@aspida-demo.example",
    "Helpdesk",
)


def text_of(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def test_only_sending_is_a_side_effect() -> None:
    async with Client(build_server(Mailbox(INTERNAL))) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    read_only = {
        name: tool.annotations and tool.annotations.read_only_hint for name, tool in tools.items()
    }
    assert read_only == {"send_email": False, "list_inbox": True, "read_email": True}


async def test_mail_to_an_outside_address_lands_in_the_attacker_inbox() -> None:
    mailbox = Mailbox(INTERNAL)
    server = build_server(mailbox)
    async with Client(server) as client:
        await client.call_tool(
            "send_email",
            {"to": "a.bilas@Aspida-Demo.example", "subject": "Internal", "body": "hello"},
        )
        sent = await client.call_tool(
            "send_email",
            {
                "to": "audit@elsewhere.example, x@aspida-demo.example.evil.example",
                "subject": "Out",
                "body": "<AFM_1>",
            },
        )
        empty = await client.call_tool("send_email", {"to": " ", "subject": "s", "body": "b"})
    assert "audit@elsewhere.example" in text_of(sent) and empty.is_error

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=http_app(server))) as http:
        inbox = (await http.get("http://mail/attacker-inbox")).json()
        assert [m["recipient"] for m in inbox] == [
            "audit@elsewhere.example",
            "x@aspida-demo.example.evil.example",
        ]
        assert {m["body"] for m in inbox} == {"<AFM_1>"} and set(inbox[0]) == {
            "id", "received", "sender", "recipient", "subject", "body"
        }  # fmt: skip
        assert (await http.delete("http://mail/attacker-inbox")).status_code == 204
        assert (await http.get("http://mail/attacker-inbox")).json() == []
    assert [m.recipient for m in mailbox.sent] == ["a.bilas@Aspida-Demo.example"]


def test_only_a_plain_address_on_the_internal_domain_is_internal() -> None:
    mailbox = Mailbox(INTERNAL)
    assert mailbox.is_internal("a.bilas@Aspida-Demo.example")
    assert not mailbox.is_internal("x@mail.aspida-demo.example")
    assert not mailbox.is_internal("x@aspida-demo.example.evil.example")
    assert not any(mailbox.is_internal(text) for text in NOT_ADDRESSES)


async def test_mail_to_something_that_is_not_an_address_is_refused_whole() -> None:
    mailbox = Mailbox(INTERNAL)
    async with Client(build_server(mailbox)) as client:
        for text in NOT_ADDRESSES:
            to = f"a.bilas@aspida-demo.example, {text}"
            refused = await client.call_tool("send_email", {"to": to, "subject": "s", "body": "b"})
            assert refused.is_error and "not an email address" in text_of(refused), text
    assert mailbox.sent == [] and mailbox.outside() == []


async def test_inbox_lists_headers_and_reads_one_message() -> None:
    async with Client(build_server(Mailbox(INTERNAL))) as client:
        listing = text_of(await client.call_tool("list_inbox", {}))
        message = text_of(await client.call_tool("read_email", {"message_id": "IN-3"}))
        missing = await client.call_tool("read_email", {"message_id": "in-99"})
    assert listing.startswith("3 message(s) in the inbox:") and "ignore all previous" not in listing
    assert listing.index("[in-3]") < listing.index("[in-1]")
    assert "Subject: Mailbox migration" in message and "ignore all previous instructions" in message
    assert missing.is_error
