"""The OpenAI Responses API through the prompt path. This is what the in-house agent calls.

Assistant text is restored for the caller. Function-call arguments are left as the model
wrote them, placeholders included: the MCP proxy decides whether a tool may see real values.
"""

import copy
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from gateway.app.core.types import Principal, Usage
from gateway.app.events.writer import EventRecord
from gateway.app.llm.client import usage_for
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
from gateway.app.proxy.payload import USER_ROLE, Reading, read_responses
from gateway.app.proxy.schemas import ResponsesRequest, UpstreamMessage
from gateway.app.proxy.upstream import Upstream, resolve_upstream
from gateway.app.vault import PLACEHOLDER_INSTRUCTION


def _shown(payload: dict[str, Any], reading: Reading) -> list[UpstreamMessage]:
    """The conversation as the model receives it: each inspected text with its role."""
    return [
        UpstreamMessage(
            role=slot.holder.get("role") or slot.holder.get("type", "item"), content=slot.read()
        )
        for slot in reading.texts
        if slot.holder is not payload and slot.key in ("content", "output", "text", "arguments")
    ]


async def _restore_item(item: dict[str, Any], restorer: Restorer, *, counted: bool) -> None:
    """Restore the text parts of a message item in place. Other item types are left alone."""
    if item.get("type") != "message":
        return
    for part in item.get("content") or []:
        if part.get("type") == "output_text" and isinstance(part.get("text"), str):
            part["text"] = await restorer.whole(part["text"], counted=counted)


def _upstream_usage(model: str, response: dict[str, Any]) -> Usage:
    usage = response.get("usage") or {}
    return usage_for(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0))


async def handle_responses(
    ctx: ProxyContext,
    principal: Principal,
    body: ResponsesRequest,
    *,
    tool_name: str | None,
    conversation: str | None,
) -> Response:
    tool = await ctx.inventory.resolve(tool_name or body.model)
    upstream = resolve_upstream(tool, ctx.settings)
    original = body.model_dump(exclude_none=True)
    if isinstance(original["input"], str):
        original["input"] = [{"role": USER_ROLE, "content": original["input"]}]
    payload = copy.deepcopy(original)
    reading, inspection = await inspect_request(
        ctx, principal, tool, read_responses, payload, conversation=conversation
    )
    authored = [index for index, slot in enumerate(reading.texts) if slot.authored]
    trace = build_trace(
        inspection,
        upstream_messages=_shown(payload, reading),
        spans=inspection.span_views(authored[-1]) if authored else [],
        forwarded=True,
    )
    verdict = await settle(ctx, principal, inspection, trace, acknowledged=None)
    if verdict.refusal is not None:
        return verdict.refusal

    if not verdict.masked:
        payload = original
    # Tool results reach the agent already masked, so placeholders can be present either way.
    payload["instructions"] = "\n\n".join(
        filter(None, [payload.get("instructions"), PLACEHOLDER_INSTRUCTION])
    )
    restorer = Restorer(ctx, inspection, active=True)
    record = inspection.event(principal, forwarded=True)

    if body.stream:
        return await _stream(ctx, upstream, payload, inspection, restorer, record)
    response = await ctx.http.post(
        f"{upstream.base_url}/responses", json=payload, headers=upstream.headers
    )
    _raise_for_upstream(response.status_code, tool.name)
    result: dict[str, Any] = response.json()
    for item in result.get("output") or []:
        await _restore_item(item, restorer, counted=True)
    result["aspida"] = trace.model_dump(mode="json")
    result["aspida_summary"] = restorer.summary().model_dump(mode="json")
    await ctx.events.write(_completed(record, inspection, upstream, body.model, result))
    return JSONResponse(result, headers=decision_headers(inspection))


def _raise_for_upstream(status_code: int, tool_name: str) -> None:
    if status_code >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{tool_name} answered with an error ({status_code})"
        )


def _completed(
    record: EventRecord,
    inspection: Inspection,
    upstream: Upstream,
    model: str,
    response: dict[str, Any],
) -> EventRecord:
    """The event with the final latency and, for the company's own model, what it cost."""
    spent = _upstream_usage(model, response) if upstream.is_company_model else Usage()
    return record.model_copy(
        update={"latency_ms": inspection.elapsed_ms(), "usage": record.usage + spent}
    )


async def _stream(
    ctx: ProxyContext,
    upstream: Upstream,
    payload: dict[str, Any],
    inspection: Inspection,
    restorer: Restorer,
    record: EventRecord,
) -> StreamingResponse:
    request = ctx.http.build_request(
        "POST", f"{upstream.base_url}/responses", json=payload, headers=upstream.headers
    )
    response = await ctx.http.send(request, stream=True)
    if response.status_code >= status.HTTP_400_BAD_REQUEST:
        await response.aclose()
        _raise_for_upstream(response.status_code, inspection.tool.name)

    async def body() -> AsyncIterator[str]:
        final: dict[str, Any] = {}
        try:
            async for event in sse.parse(response.aiter_lines()):
                data = event.json()
                async for restored in _restore_event(data, restorer):
                    yield sse.encode(restored, restored.get("type"))
                if data.get("type") in ("response.completed", "response.incomplete"):
                    final = data.get("response") or {}
        except httpx.HTTPError:
            error = {"type": "error", "message": "The model stopped answering"}
            yield sse.encode(error, "error")
        finally:
            await response.aclose()
            record_after_stream(
                ctx, _completed(record, inspection, upstream, payload["model"], final)
            )

    return StreamingResponse(
        body(), media_type="text/event-stream", headers=decision_headers(inspection)
    )


async def _restore_event(
    event: dict[str, Any], restorer: Restorer
) -> AsyncIterator[dict[str, Any]]:
    """Restore placeholders in one stream event. Deltas go through the streaming rehydrator;
    the complete texts repeated in later events are restored without being counted twice."""
    kind = event.get("type")
    stream = f"{event.get('item_id')}:{event.get('content_index')}"
    if kind == "response.output_text.delta":
        event["delta"] = await restorer.feed(stream, event.get("delta", ""))
        if event["delta"]:
            yield event
        return
    if kind == "response.output_text.done":
        if tail := restorer.flush(stream):
            yield {**event, "type": "response.output_text.delta", "delta": tail}
        event["text"] = await restorer.whole(event.get("text", ""), counted=False)
    elif kind == "response.content_part.done":
        part = event.get("part") or {}
        if part.get("type") == "output_text":
            part["text"] = await restorer.whole(part.get("text", ""), counted=False)
    elif kind == "response.output_item.done":
        await _restore_item(event.get("item") or {}, restorer, counted=False)
    elif kind in ("response.completed", "response.incomplete"):
        for item in (event.get("response") or {}).get("output") or []:
            await _restore_item(item, restorer, counted=False)
    yield event
