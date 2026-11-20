"""The Responses path: assistant text is restored, function-call arguments are not."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import SecretStr

from gateway.app.config import Settings
from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action, ToolStatus
from gateway.app.proxy import sse
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.inspection import Inspector
from gateway.app.proxy.responses import handle_responses
from gateway.app.proxy.schemas import ResponsesRequest
from gateway.app.proxy.upstream import COMPANY_ASSISTANT
from gateway.app.vault import PLACEHOLDER_INSTRUCTION
from gateway.tests.proxy.fakes import (
    FakeDetector,
    FakeEvents,
    FakeInventory,
    FakePolicy,
    FakeVault,
)

AFM = "094014201"
PROMPT = f"Email the tax number {AFM} of Maria Papadopoulou to the accountant."
CHUNK = 4
MODEL = "gpt-6-luna"
MODEL_URL = "http://model.test/v1"
KEY = "test-key"

model = FastAPI()
received: list[dict[str, Any]] = []
credentials: list[str | None] = []


def _output(text: str) -> list[dict[str, Any]]:
    """A model turn that says the user's text back and calls a tool with it."""
    return [
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "mail.send_email",
            "arguments": json.dumps({"body": text}),
        },
    ]


@model.post("/v1/responses", response_model=None)
async def fake_model(request: Request) -> Response:
    body = await request.json()
    received.append(body)
    credentials.append(request.headers.get("authorization"))
    text = body["input"][-1]["content"]
    output = _output(text)
    final = {"id": "resp_1", "output": output, "usage": {"input_tokens": 40, "output_tokens": 9}}
    if not body.get("stream"):
        return Response(json.dumps(final), media_type="application/json")

    async def events() -> AsyncIterator[str]:
        where = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
        for start in range(0, len(text), CHUNK):
            delta = {"type": "response.output_text.delta", "delta": text[start : start + CHUNK]}
            yield sse.encode({**delta, **where}, delta["type"])
        done = {"type": "response.output_text.done", "text": text, **where}
        yield sse.encode(done, done["type"])
        for item in output:
            yield sse.encode(
                {"type": "response.output_item.done", "item": item}, "response.output_item.done"
            )
        yield sse.encode({"type": "response.completed", "response": final}, "response.completed")

    return StreamingResponse(events(), media_type="text/event-stream")


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[ProxyContext]:
    received.clear()
    credentials.clear()
    vault = FakeVault()
    transport = httpx.ASGITransport(app=model)
    # The company assistant is OpenAI with the gateway's key; here its address is the fake.
    with_key = settings.model_copy(
        update={"openai_api_key": SecretStr(KEY), "openai_base_url": MODEL_URL}
    )
    async with httpx.AsyncClient(transport=transport) as http:
        yield ProxyContext(
            settings=with_key,
            pseudonym_key=b"p" * 32,
            inspector=Inspector(FakeDetector(), vault, _RedactEverything()),
            vault=vault,
            inventory=FakeInventory(),
            events=FakeEvents(),
            http=http,
        )


class _RedactEverything(FakePolicy):
    """The company assistant is approved, and its prompts are still masked."""

    BY_STATUS: ClassVar = dict.fromkeys(ToolStatus, Action.REDACT)


async def _send(ctx: ProxyContext, *, stream: bool) -> Response:
    body = ResponsesRequest(
        model=MODEL,
        instructions="You are a helpdesk assistant.",
        input=[{"role": "user", "content": PROMPT}],
        stream=stream,
    )
    return await handle_responses(
        ctx, DEMO_USERS[0], body, tool_name=COMPANY_ASSISTANT, conversation="s1"
    )


def _assert_model_saw_placeholders_only() -> None:
    (request,) = received
    sent = json.dumps(request, ensure_ascii=False)
    assert AFM not in sent and "Maria Papadopoulou" not in sent
    assert "<AFM_1>" in sent and request["instructions"].endswith(PLACEHOLDER_INSTRUCTION)
    assert credentials == [f"Bearer {KEY}"]


async def test_text_is_restored_and_tool_arguments_keep_placeholders(ctx: ProxyContext) -> None:
    response = await _send(ctx, stream=False)
    message, call = json.loads(bytes(response.body))["output"]
    assert message["content"][0]["text"] == PROMPT
    assert AFM not in call["arguments"] and "<AFM_1>" in call["arguments"]
    _assert_model_saw_placeholders_only()
    assert isinstance(ctx.events, FakeEvents)
    assert ctx.events.records[0].usage.input_tokens == 40


async def test_stream_restores_deltas_and_final_items(ctx: ProxyContext) -> None:
    response = await _send(ctx, stream=True)
    assert isinstance(response, StreamingResponse)
    raw = "".join([chunk async for chunk in response.body_iterator])  # type: ignore[misc]
    await asyncio.sleep(0)
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]

    deltas = [e["delta"] for e in events if e["type"] == "response.output_text.delta"]
    assert "".join(deltas) == PROMPT
    done = next(e for e in events if e["type"] == "response.output_text.done")
    assert done["text"] == PROMPT
    message, call = events[-1]["response"]["output"]
    assert message["content"][0]["text"] == PROMPT
    assert "<AFM_1>" in call["arguments"] and AFM not in call["arguments"]
    assert "event: response.completed" in raw
    _assert_model_saw_placeholders_only()
