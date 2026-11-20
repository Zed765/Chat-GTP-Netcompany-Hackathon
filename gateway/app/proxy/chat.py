"""OpenAI Chat Completions through the prompt path."""

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from gateway.app.core.types import Principal
from gateway.app.events.writer import EventRecord
from gateway.app.proxy import sse
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.inspection import Inspection
from gateway.app.proxy.outcome import (
    Restorer,
    build_trace,
    decision_headers,
    inspect_request,
    record_after_stream,
    settle,
)
from gateway.app.proxy.payload import read_chat
from gateway.app.proxy.schemas import ChatCompletionRequest, Trace, UpstreamMessage
from gateway.app.proxy.upstream import Upstream, resolve_upstream
from gateway.app.vault import PLACEHOLDER_INSTRUCTION


def _as_upstream_messages(messages: list[dict[str, Any]]) -> list[UpstreamMessage]:
    shown: list[UpstreamMessage] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(part["text"] for part in content if part.get("type") == "text")
        shown.append(UpstreamMessage(role=message["role"], content=content or ""))
    return shown


async def handle_chat(
    ctx: ProxyContext,
    principal: Principal,
    body: ChatCompletionRequest,
    *,
    tool_name: str | None,
    conversation: str | None,
    acknowledged: str | None,
) -> Response:
    tool = await ctx.inventory.resolve(tool_name or body.model)
    upstream = resolve_upstream(tool, ctx.settings)
    original = body.model_dump(exclude_none=True)
    payload = copy.deepcopy(original)
    reading, inspection = await inspect_request(
        ctx, principal, tool, read_chat, payload, conversation=conversation
    )
    authored = [index for index, slot in enumerate(reading.texts) if slot.authored]
    trace = build_trace(
        inspection,
        upstream_messages=_as_upstream_messages(payload["messages"]),
        spans=inspection.span_views(authored[-1]) if authored else [],
        forwarded=True,
    )
    verdict = await settle(ctx, principal, inspection, trace, acknowledged=acknowledged)
    if verdict.refusal is not None:
        return verdict.refusal

    if not verdict.masked:
        payload = original
        shown = _as_upstream_messages(payload["messages"])
        trace = trace.model_copy(update={"upstream_messages": shown})
    elif inspection.placeholders:
        note = {"role": "system", "content": PLACEHOLDER_INSTRUCTION}
        payload["messages"] = [note, *payload["messages"]]
        # The note is part of what the tool sees, so the trace shows it too.
        shown = _as_upstream_messages(payload["messages"])
        trace = trace.model_copy(update={"upstream_messages": shown})
    restorer = Restorer(ctx, inspection, active=verdict.masked)
    # An acknowledged warning already has its event; everything else is recorded on completion.
    record = None if verdict.recorded else inspection.event(principal, forwarded=True)

    if body.stream:
        return await _stream(ctx, upstream, payload, inspection, trace, restorer, record)
    response = await ctx.http.post(
        f"{upstream.base_url}/chat/completions", json=payload, headers=upstream.headers
    )
    _raise_for_upstream(response.status_code, tool.name)
    completion: dict[str, Any] = response.json()
    for choice in completion.get("choices", []):
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            message["content"] = await restorer.whole(message["content"])
    completion["aspida"] = trace.model_dump(mode="json")
    completion["aspida_summary"] = restorer.summary().model_dump(mode="json")
    if record is not None:
        await ctx.events.write(record.model_copy(update={"latency_ms": inspection.elapsed_ms()}))
    return JSONResponse(completion, headers=decision_headers(inspection))


def _raise_for_upstream(status_code: int, tool_name: str) -> None:
    if status_code >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{tool_name} answered with an error ({status_code})"
        )


async def _stream(
    ctx: ProxyContext,
    upstream: Upstream,
    payload: dict[str, Any],
    inspection: Inspection,
    trace: Trace,
    restorer: Restorer,
    record: EventRecord | None,
) -> StreamingResponse:
    request = ctx.http.build_request(
        "POST", f"{upstream.base_url}/chat/completions", json=payload, headers=upstream.headers
    )
    response = await ctx.http.send(request, stream=True)
    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        await response.aclose()
        _raise_for_upstream(response.status_code, inspection.tool.name)

    def envelope(**extra: Any) -> str:
        chunk = {
            "id": f"chatcmpl-{inspection.trace_id}",
            "object": "chat.completion.chunk",
            "model": payload["model"],
            "choices": [],
        }
        return sse.encode({**chunk, **extra})

    async def body() -> AsyncIterator[str]:
        try:
            yield envelope(aspida=trace.model_dump(mode="json"))
            async for event in sse.parse(response.aiter_lines()):
                if event.data == sse.DONE:
                    break
                async for chunk in _restore_chunk(event.json(), restorer):
                    yield sse.encode(chunk)
            yield envelope(aspida_summary=restorer.summary().model_dump(mode="json"))
            yield sse.ServerEvent(sse.DONE).encode()
        except httpx.HTTPError:
            yield sse.encode(
                {"error": {"message": "The AI tool stopped answering", "type": "upstream_error"}}
            )
        finally:
            await response.aclose()
            if record is not None:
                record_after_stream(
                    ctx, record.model_copy(update={"latency_ms": inspection.elapsed_ms()})
                )

    return StreamingResponse(
        body(), media_type="text/event-stream", headers=decision_headers(inspection)
    )


async def _restore_chunk(
    chunk: dict[str, Any], restorer: Restorer
) -> AsyncIterator[dict[str, Any]]:
    """Restore placeholders in one streamed chunk. Text still held back when a choice
    finishes is released in an extra chunk just before the final one."""
    for choice in chunk.get("choices", []):
        stream = str(choice.get("index", 0))
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            delta["content"] = await restorer.feed(stream, delta["content"])
        if choice.get("finish_reason") and (tail := restorer.flush(stream)):
            held_back = {"index": choice.get("index", 0), "delta": {"content": tail}}
            yield {**chunk, "choices": [{**held_back, "finish_reason": None}]}
    yield chunk
