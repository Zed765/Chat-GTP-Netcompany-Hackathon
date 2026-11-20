"""The prompt path end to end against the fake AI tools, with stand-in detector, vault
and policy. The real modules are covered by their own tests and by `make smoke`."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.responses import Response, StreamingResponse

from gateway.app.config import Settings
from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action
from gateway.app.proxy.chat import handle_chat
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.inspection import Inspector
from gateway.app.proxy.schemas import ChatCompletionRequest
from gateway.tests.proxy.fakes import (
    FakeDetector,
    FakeEvents,
    FakeInventory,
    FakePolicy,
    FakeVault,
)
from mock_upstream.main import app as upstream_app
from mock_upstream.tests.fakes import OPENING, fake_model

EMPLOYEE = DEMO_USERS[0]
AFM = "094014201"
IBAN = "GR1601101250000000012300695"
PROMPT = f"Reply to Maria Papadopoulou, tax number {AFM}, account {IBAN}."
REAL_VALUES = ("Maria Papadopoulou", AFM, IBAN)


@pytest.fixture
async def ctx(settings: Settings) -> AsyncIterator[ProxyContext]:
    vault = FakeVault()
    transport = httpx.ASGITransport(app=upstream_app)
    with fake_model():
        async with httpx.AsyncClient(transport=transport, base_url="http://mock-upstream") as http:
            await http.delete("/recordings")
            yield ProxyContext(
                settings=settings,
                pseudonym_key=b"p" * 32,
                inspector=Inspector(FakeDetector(), vault, FakePolicy()),
                vault=vault,
                inventory=FakeInventory(),
                events=FakeEvents(),
                http=http,
            )


async def _send(
    ctx: ProxyContext, tool: str, text: str, *, stream: bool = False, ack: str | None = None
) -> Response:
    body = ChatCompletionRequest(
        model="demo", messages=[{"role": "user", "content": text}], stream=stream
    )
    return await handle_chat(
        ctx, EMPLOYEE, body, tool_name=tool, conversation="c1", acknowledged=ack
    )


def _json(response: Response) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(bytes(response.body))
    return loaded


async def _recorded(ctx: ProxyContext) -> str:
    return (await ctx.http.get("/recordings")).text


def _events(ctx: ProxyContext) -> FakeEvents:
    assert isinstance(ctx.events, FakeEvents)
    return ctx.events


async def test_redact_masks_upstream_and_restores_the_answer(ctx: ProxyContext) -> None:
    response = await _send(ctx, "chatterbox-ai", PROMPT)
    body = _json(response)
    assert body["choices"][0]["message"]["content"] == OPENING + PROMPT

    recorded = await _recorded(ctx)
    assert all(value not in recorded for value in REAL_VALUES)
    assert "<PERSON_1>" in recorded and "<AFM_1>" in recorded

    trace = body["aspida"]
    assert trace["action"] == "redact" and trace["forwarded"] is True
    assert [span["data_type"] for span in trace["spans"]] == ["PERSON", "AFM", "IBAN"]
    assert PROMPT[trace["spans"][1]["start"] : trace["spans"][1]["end"]] == AFM
    assert all(value not in json.dumps(trace) for value in REAL_VALUES)
    assert body["aspida_summary"]["rehydration"] == {"sent": 3, "returned": 3, "unresolved": []}

    (event,) = _events(ctx).records
    assert event.action is Action.REDACT and event.data_counts == {"PERSON": 1, "AFM": 1, "IBAN": 1}
    assert event.masked_snippet and all(v not in event.masked_snippet for v in REAL_VALUES)


async def test_stream_restores_placeholders_split_across_chunks(ctx: ProxyContext) -> None:
    response = await _send(ctx, "echo", PROMPT, stream=True)
    assert isinstance(response, StreamingResponse)
    raw = "".join([chunk async for chunk in response.body_iterator])  # type: ignore[misc]
    await asyncio.sleep(0)
    chunks = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: {")]

    assert chunks[0]["aspida"]["action"] == "redact" and chunks[0]["choices"] == []
    text = "".join(
        choice["delta"].get("content", "") for chunk in chunks for choice in chunk["choices"]
    )
    assert text == PROMPT
    assert chunks[-1]["aspida_summary"]["rehydration"]["returned"] == 3
    assert raw.rstrip().endswith("data: [DONE]")
    recorded = await _recorded(ctx)
    assert all(value not in recorded for value in REAL_VALUES)
    assert len(_events(ctx).records) == 1


async def test_allow_forwards_the_prompt_unchanged(ctx: ProxyContext) -> None:
    body = _json(await _send(ctx, "athena-assist", PROMPT))
    assert body["aspida"]["action"] == "allow"
    assert body["aspida"]["upstream_messages"][-1]["content"] == PROMPT
    assert AFM in await _recorded(ctx)


async def test_block_forwards_nothing(ctx: ProxyContext) -> None:
    response = await _send(ctx, "chatterbox-ai", "Use the key sk-test-abcd1234 please")
    body = _json(response)
    assert response.status_code == 403
    assert body["error"]["type"] == "aspida_policy_block"
    assert body["aspida"]["needs_acknowledgement"] is False
    assert await _recorded(ctx) == "[]"
    (event,) = _events(ctx).records
    assert event.action is Action.BLOCK and event.forwarded is False


async def test_warning_needs_acknowledgement_then_sends_the_masked_version(
    ctx: ProxyContext,
) -> None:
    warned = await _send(ctx, "draftpilot", PROMPT)
    body = _json(warned)
    assert warned.status_code == 409 and body["aspida"]["needs_acknowledgement"] is True
    assert "<AFM_1>" in body["aspida"]["upstream_messages"][-1]["content"]
    assert await _recorded(ctx) == "[]"

    trace_id = body["aspida"]["trace_id"]
    sent = _json(await _send(ctx, "draftpilot", PROMPT, ack=trace_id))
    assert AFM in sent["choices"][0]["message"]["content"]
    recorded = await _recorded(ctx)
    assert all(value not in recorded for value in REAL_VALUES)
    events = _events(ctx)
    assert len(events.records) == 1 and events.acknowledged == [trace_id]


async def test_placeholders_are_stable_across_turns(ctx: ProxyContext) -> None:
    await _send(ctx, "chatterbox-ai", PROMPT)
    second = _json(await _send(ctx, "chatterbox-ai", f"Again about {AFM} for Maria Papadopoulou"))
    assert second["aspida"]["upstream_messages"][-1]["content"] == (
        "Again about <AFM_1> for <PERSON_1>"
    )


async def test_tool_without_an_endpoint_is_refused(ctx: ProxyContext) -> None:
    with pytest.raises(Exception, match="no API endpoint"):
        await _send(ctx, "some-real-tool.example", "hello")


async def test_vault_is_scoped_to_the_user_not_just_the_conversation_id(ctx: ProxyContext) -> None:
    await _send(ctx, "chatterbox-ai", PROMPT)
    assert isinstance(ctx.vault, FakeVault)
    (vault_id,) = ctx.vault.values
    assert vault_id.endswith(":c1") and vault_id != "c1" and EMPLOYEE.user_id not in vault_id
