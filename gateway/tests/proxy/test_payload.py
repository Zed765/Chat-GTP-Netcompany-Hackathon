"""Every field of a request is read: free text is masked, a name that holds a real value
refuses the request, and what cannot be inspected is refused by name."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from gateway.app.config import Settings
from gateway.app.core.auth import DEMO_USERS
from gateway.app.proxy.chat import handle_chat
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.inspection import Inspector
from gateway.app.proxy.payload import UninspectedError, read_chat, read_responses
from gateway.app.proxy.responses import handle_responses
from gateway.app.proxy.schemas import ChatCompletionRequest, ResponsesRequest
from gateway.tests.proxy.fakes import (
    FakeDetector,
    FakeEvents,
    FakeInventory,
    FakePolicy,
    FakeVault,
)

AFM = "094014201"
IBAN = "GR1601101250000000012300695"
NAME = "Maria Papadopoulou"
SENSITIVE = f"{NAME} AFM {AFM} IBAN {IBAN}"
REAL_VALUES = (NAME, AFM, IBAN)
HELLO = {"role": "user", "content": "hello"}
IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
ENCRYPTED_REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "x"}

upstream = FastAPI()
received: list[dict[str, Any]] = []


@upstream.post("/{path:path}", response_model=None)
async def record(request: Request) -> Response:
    received.append(await request.json())
    answer = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "output": []}
    return Response(json.dumps(answer), media_type="application/json")


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[ProxyContext]:
    received.clear()
    vault = FakeVault()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream)) as http:
        yield ProxyContext(
            settings=settings,
            pseudonym_key=b"p" * 32,
            inspector=Inspector(FakeDetector(), vault, FakePolicy()),
            vault=vault,
            inventory=FakeInventory(),
            events=FakeEvents(),
            http=http,
        )


async def _chat(ctx: ProxyContext, tool: str, **body: Any) -> Response:
    request = ChatCompletionRequest(**({"model": "demo"} | body))
    return await handle_chat(
        ctx, DEMO_USERS[0], request, tool_name=tool, conversation="c", acknowledged=None
    )


async def _respond(ctx: ProxyContext, tool: str, **body: Any) -> Response:
    request = ResponsesRequest(**({"model": "demo"} | body))
    return await handle_responses(ctx, DEMO_USERS[0], request, tool_name=tool, conversation="c")


def _sent() -> str:
    return json.dumps(received[-1], ensure_ascii=False)


def _tool(**function: Any) -> dict[str, Any]:
    return {"type": "function", "function": {"name": "lookup", **function}}


def _parameters(**keywords: Any) -> dict[str, Any]:
    return {"type": "object", "properties": {"q": {"type": "string", **keywords}}}


def _call(**call: Any) -> dict[str, Any]:
    function = {"name": "lookup", "arguments": "{}"} | call.pop("function", {})
    return {"id": "call_1", "type": "function", "function": function} | call


def _said(*parts: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"role": "user", "content": list(parts)}]


async def test_tool_definitions_and_past_tool_calls_are_masked_like_messages(
    ctx: ProxyContext,
) -> None:
    messages = [
        {"role": "user", "content": f"Look up {NAME}"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "crm.find", "arguments": json.dumps({"afm": AFM})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": f"{NAME} has tax number {AFM}"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "crm.find",
                "description": f"Find a client, for example {NAME} with tax number {AFM}",
                "parameters": {"type": "object", "properties": {"afm": {"type": "string"}}},
            },
        }
    ]
    response = await _chat(ctx, "chatterbox-ai", messages=messages, tools=tools)
    assert response.status_code == 200
    sent = _sent()
    assert AFM not in sent and NAME not in sent
    assert sent.count("<AFM_1>") == 3 and received[-1]["tools"][0]["function"]["name"] == "crm.find"


async def test_responses_instructions_and_tool_descriptions_are_masked(ctx: ProxyContext) -> None:
    await _respond(
        ctx,
        "chatterbox-ai",
        instructions=f"You help {NAME}, tax number {AFM}.",
        input=[
            {"role": "user", "content": "Hello"},
            {
                "type": "function_call",
                "call_id": "c1",
                "name": "f",
                "arguments": f'{{"q": "{AFM}"}}',
            },
            {"type": "function_call_output", "call_id": "c1", "output": f"Found {NAME}"},
        ],
        tools=[{"type": "function", "name": "f", "description": f"Search for {NAME}"}],
    )
    sent = _sent()
    assert AFM not in sent and NAME not in sent
    assert "<PERSON_1>" in received[-1]["instructions"]
    assert "<PERSON_1>" in received[-1]["tools"][0]["description"]


CHAT_FIELDS: dict[str, dict[str, Any]] = {
    "stop": {"stop": [SENSITIVE]},
    "model": {"model": SENSITIVE},
    "tool_choice": {"tool_choice": {"type": "function", "function": {"name": SENSITIVE}}},
    "stream_options": {"stream_options": {"note": SENSITIVE}},
    "reasoning": {"reasoning": {"effort": SENSITIVE}},
    "include": {"include": [SENSITIVE]},
    "service_tier": {"service_tier": SENSITIVE},
    "response format name": {
        "response_format": {"type": "json_schema", "json_schema": {"name": SENSITIVE}}
    },
    "response format enum": {
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "string", "enum": [SENSITIVE]}},
        }
    },
    "message name": {"messages": [HELLO | {"name": SENSITIVE}]},
    "message refusal": {"messages": [HELLO, {"role": "assistant", "refusal": SENSITIVE}]},
    "tool_call_id": {
        "messages": [HELLO, {"role": "tool", "tool_call_id": SENSITIVE, "content": "ok"}]
    },
    "role": {"messages": [{"role": SENSITIVE, "content": "hello"}]},
    "function name": {"tools": [_tool(name=SENSITIVE)]},
    "parameter enum": {"tools": [_tool(parameters=_parameters(enum=[SENSITIVE]))]},
    "parameter default": {"tools": [_tool(parameters=_parameters(default=SENSITIVE))]},
    "parameter default number": {"tools": [_tool(parameters=_parameters(default=int(AFM)))]},
    "parameter title": {"tools": [_tool(parameters=_parameters(title=SENSITIVE))]},
    "parameter examples": {"tools": [_tool(parameters=_parameters(examples=[[SENSITIVE]]))]},
    "property name": {
        "tools": [_tool(parameters={"type": "object", "properties": {SENSITIVE: {}}})]
    },
    "description that is not a string": {"tools": [_tool(description={"text": SENSITIVE})]},
    "legacy function name": {"functions": [{"name": SENSITIVE}]},
    "refusal part": {"messages": _said({"type": "refusal", "refusal": SENSITIVE})},
    "reasoning part": {"messages": _said({"type": "reasoning", "text": SENSITIVE})},
    "extra key on a text part": {
        "messages": _said({"type": "text", "text": "hello", "note": SENSITIVE})
    },
    "tool call id": {"messages": [HELLO, {"role": "assistant", "tool_calls": [_call(id=AFM)]}]},
    "tool call function name": {
        "messages": [
            HELLO,
            {"role": "assistant", "tool_calls": [_call(function={"name": SENSITIVE})]},
        ]
    },
    "function_call name": {
        "messages": [
            HELLO,
            {"role": "assistant", "function_call": {"name": SENSITIVE, "arguments": "{}"}},
        ]
    },
    "a key the gateway does not know": {SENSITIVE: True},
}

RESPONSES_FIELDS: dict[str, dict[str, Any]] = {
    "reasoning summary": {
        "input": [
            HELLO,
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": SENSITIVE}],
            },
        ]
    },
    "encrypted reasoning": {"input": [HELLO, ENCRYPTED_REASONING | {"id": SENSITIVE}]},
    "call_id": {
        "input": [HELLO, {"type": "function_call_output", "call_id": SENSITIVE, "output": "ok"}]
    },
    "function call name": {
        "input": [
            HELLO,
            {"type": "function_call", "call_id": "c1", "name": SENSITIVE, "arguments": "{}"},
        ]
    },
    "item id": {"input": [HELLO | {"id": SENSITIVE}]},
    "item status": {"input": [HELLO | {"status": SENSITIVE}]},
    "item type": {"input": [HELLO | {"type": SENSITIVE}]},
    "annotations": {
        "input": [
            {
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "ok", "annotations": [{"title": SENSITIVE}]}
                ],
            }
        ]
    },
    "tool name": {"tools": [{"type": "function", "name": SENSITIVE}]},
    "tool schema": {
        "tools": [{"type": "function", "name": "f", "parameters": _parameters(enum=[SENSITIVE])}]
    },
    "text format": {
        "text": {"format": {"type": "json_schema", "name": SENSITIVE, "schema": {}}},
    },
    "reasoning effort": {"reasoning": {"effort": SENSITIVE}},
}


def _assert_nothing_real_left(refused: HTTPException | None) -> None:
    if refused is not None:
        assert refused.status_code == 400 and not received
        assert not any(value in str(refused.detail) for value in REAL_VALUES)
        return
    assert not any(value in _sent() for value in REAL_VALUES), _sent()


@pytest.mark.parametrize("extra", CHAT_FIELDS.values(), ids=CHAT_FIELDS.keys())
async def test_a_real_value_in_any_chat_field_is_masked_or_refused(
    ctx: ProxyContext, extra: dict[str, Any]
) -> None:
    refused = None
    try:
        await _chat(ctx, "chatterbox-ai", **({"messages": [HELLO]} | extra))
    except HTTPException as exc:
        refused = exc
    _assert_nothing_real_left(refused)


@pytest.mark.parametrize("extra", RESPONSES_FIELDS.values(), ids=RESPONSES_FIELDS.keys())
async def test_a_real_value_in_any_responses_field_is_masked_or_refused(
    ctx: ProxyContext, extra: dict[str, Any]
) -> None:
    refused = None
    try:
        await _respond(ctx, "chatterbox-ai", **({"input": [HELLO]} | extra))
    except HTTPException as exc:
        refused = exc
    _assert_nothing_real_left(refused)


async def test_a_refusal_names_the_field_and_what_was_found_in_it(ctx: ProxyContext) -> None:
    tools = [_tool(), _tool(parameters=_parameters(enum=["plain", f"x {AFM}"]))]
    with pytest.raises(HTTPException) as refused:
        await _chat(ctx, "athena-assist", messages=[HELLO], tools=tools)
    assert refused.value.status_code == 400 and not received
    assert "`tools[1].function.parameters.properties[0].enum[1]`" in refused.value.detail
    assert "AFM" in refused.value.detail and AFM not in refused.value.detail


@pytest.mark.parametrize(
    ("body", "where"),
    [
        ({"messages": [{"role": "User", "content": "hi"}]}, "messages[0].role"),
        ({"messages": [HELLO], "temperature": "hot"}, "temperature"),
        ({"messages": [HELLO], "stream_options": {"include_usage": "yes"}}, "include_usage"),
        ({"messages": [HELLO], "tools": [{"type": "retrieval"}]}, "tools[0].type"),
    ],
)
async def test_a_value_outside_its_closed_set_is_refused(
    ctx: ProxyContext, body: dict[str, Any], where: str
) -> None:
    with pytest.raises(HTTPException) as refused:
        await _chat(ctx, "chatterbox-ai", **body)
    assert refused.value.status_code == 400 and where in refused.value.detail
    assert not received


@pytest.mark.parametrize(
    "extra",
    [{"user": "v.tsioutsias"}, {"metadata": {"client": NAME}}, {"previous_response_id": "resp_1"}],
)
async def test_a_field_the_gateway_does_not_inspect_is_refused(
    ctx: ProxyContext, extra: dict[str, Any]
) -> None:
    with pytest.raises(HTTPException) as refused:
        await _chat(ctx, "chatterbox-ai", messages=[HELLO], **extra)
    assert refused.value.status_code == 400 and next(iter(extra)) in refused.value.detail
    assert not received


async def test_an_image_is_refused_unless_the_tool_is_approved(ctx: ProxyContext) -> None:
    messages = [{"role": "user", "content": [{"type": "text", "text": "What is this?"}, IMAGE]}]
    with pytest.raises(HTTPException, match="image_url"):
        await _chat(ctx, "chatterbox-ai", messages=messages)
    assert not received
    assert (await _chat(ctx, "athena-assist", messages=messages)).status_code == 200


async def test_encrypted_reasoning_is_refused_unless_the_tool_is_approved(
    ctx: ProxyContext,
) -> None:
    items = [HELLO, ENCRYPTED_REASONING]
    with pytest.raises(HTTPException, match="encrypted_content"):
        await _respond(ctx, "chatterbox-ai", input=items)
    assert not received
    assert (await _respond(ctx, "athena-assist", input=items)).status_code == 200


def test_the_agents_own_request_is_accepted() -> None:
    """What the in-house agent sends: function tools as the MCP servers describe them, and
    the model's own output items of the turns before."""
    payload = {
        "model": "gpt-6-luna",
        "instructions": "You are the helpdesk assistant.",
        "input": [
            {"role": "user", "content": "Find the client"},
            ENCRYPTED_REASONING,
            {
                "type": "function_call",
                "id": "fc_0f3a9c2e4b6d8f1a3c5e7b9d",
                "call_id": "call_0f3a9c2e4b6d8f1a3c5e7b9d",
                "name": "crm__search_clients",
                "arguments": '{"query": "Helios"}',
                "status": "completed",
            },
            {
                "type": "function_call_output",
                "call_id": "call_0f3a9c2e4b6d8f1a3c5e7b9d",
                "output": "1 client found",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Found it", "annotations": [], "logprobs": []}
                ],
            },
        ],
        "tools": [
            {
                "type": "function",
                "name": "crm__search_clients",
                "description": "Search the CRM.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "default": "",
                            "description": "Name, alias or AFM",
                            "title": "Query",
                            "type": "string",
                        },
                        "limit": {
                            "default": 10,
                            "maximum": 25,
                            "minimum": 1,
                            "title": "Limit",
                            "type": "integer",
                        },
                    },
                    "required": ["query"],
                    "title": "search_clientsArguments",
                },
                "strict": False,
            }
        ],
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
        "reasoning": {"effort": "low"},
        "include": ["reasoning.encrypted_content"],
    }
    reading = read_responses(payload, opaque_allowed=True)
    assert [slot.read() for slot in reading.texts] == [
        "You are the helpdesk assistant.",
        "Search the CRM.",
        "Name, alias or AFM",
        "Find the client",
        '{"query": "Helios"}',
        "1 client found",
        "Found it",
    ]
    assert reading.texts[0].instructions and reading.texts[3].authored
    assert {"crm__search_clients", "Query", "limit", "10", "msg_1"} <= {
        name.value for name in reading.names
    }


def test_only_what_a_user_said_is_marked_as_authored() -> None:
    payload = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": [{"type": "text", "text": "three"}]},
        ],
        "tools": [_tool(description="four")],
    }
    reading = read_chat(payload, opaque_allowed=False)
    assert [(slot.read(), slot.authored) for slot in reading.texts] == [
        ("four", False),
        ("one", True),
        ("two", False),
        ("three", True),
    ]


def test_an_unknown_item_type_is_refused() -> None:
    payload = {"model": "m", "input": [{"type": "web_search_call", "id": "ws_1"}]}
    with pytest.raises(UninspectedError, match="web_search_call"):
        read_responses(payload, opaque_allowed=False)
    with pytest.raises(UninspectedError, match="audio"):
        read_chat({"model": "m", "messages": [], "audio": {"voice": "x"}}, opaque_allowed=True)
