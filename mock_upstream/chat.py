"""Stand-ins for public AI tools. Each speaks the OpenAI Chat Completions API, answers with
the real model and records exactly what it received, so the leak checks can prove that no
real value ever got this far."""

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from pydantic import BaseModel, ConfigDict, Field

from mock_upstream.settings import get_settings

router = APIRouter(tags=["fake AI tools"])

ECHO = "echo"
TOOLS = frozenset({"athena-assist", "draftpilot", "chatterbox-ai", ECHO})
MAX_RECORDINGS = 2000
OPENAI_BASE_URL = "https://api.openai.com/v1"
# Small pieces, so placeholders get split across chunks the way a real model splits them.
CHUNK_CHARS = 5
CHUNK_DELAY_S = 0.012


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "mock"
    messages: list[Message] = Field(min_length=1)
    stream: bool = False


class Recording(BaseModel):
    tool: str
    received: datetime
    body: dict[str, Any]


_recordings: deque[Recording] = deque(maxlen=MAX_RECORDINGS)


def _last_user_message(request: ChatRequest) -> str:
    return next((m.content for m in reversed(request.messages) if m.role == "user"), "")


@lru_cache
def openai_client() -> AsyncOpenAI:
    settings = get_settings()
    # An explicit address: the SDK would otherwise read an empty OPENAI_BASE_URL.
    return AsyncOpenAI(
        api_key=settings.api_key, base_url=settings.openai_base_url or OPENAI_BASE_URL
    )


# How the demo tools answer, whichever of them is asked.
HOUSE_STYLE = (
    "Answer directly. When you draft an email or a letter, write only its body: no subject "
    "line unless the user asks for one."
)


async def _answer(tool: str, request: ChatRequest, client: AsyncOpenAI) -> str:
    """The echo tool says the prompt back, for round-trip checks; the others ask the model."""
    if tool == ECHO:
        return _last_user_message(request)
    response = await client.responses.create(
        model=get_settings().model,
        instructions=HOUSE_STYLE,
        input=cast(
            ResponseInputParam, [{"role": m.role, "content": m.content} for m in request.messages]
        ),
        reasoning={"effort": "low"},
        store=False,
    )
    return response.output_text


def _envelope(completion_id: str, model: str, kind: str, choice: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": kind,
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, **choice}],
    }


async def _stream(completion_id: str, model: str, text: str) -> AsyncIterator[str]:
    def event(delta: dict[str, str], finish: str | None = None) -> str:
        chunk = _envelope(
            completion_id, model, "chat.completion.chunk", {"delta": delta, "finish_reason": finish}
        )
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    yield event({"role": "assistant", "content": ""})
    for start in range(0, len(text), CHUNK_CHARS):
        yield event({"content": text[start : start + CHUNK_CHARS]})
        await asyncio.sleep(CHUNK_DELAY_S)
    yield event({}, finish="stop")
    yield "data: [DONE]\n\n"


@router.post("/tools/{tool}/v1/chat/completions", response_model=None)
async def chat_completions(
    tool: str, request: ChatRequest, client: Annotated[AsyncOpenAI, Depends(openai_client)]
) -> StreamingResponse | dict[str, Any]:
    if tool not in TOOLS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such AI tool")
    _recordings.append(
        Recording(tool=tool, received=datetime.now(UTC), body=request.model_dump(mode="json"))
    )
    text = await _answer(tool, request, client)
    completion_id = f"chatcmpl-{uuid4().hex}"
    if request.stream:
        return StreamingResponse(
            _stream(completion_id, request.model, text), media_type="text/event-stream"
        )
    message = {"role": "assistant", "content": text}
    return _envelope(
        completion_id,
        request.model,
        "chat.completion",
        {"message": message, "finish_reason": "stop"},
    )


@router.get("/recordings")
async def recordings(tool: str | None = None) -> list[Recording]:
    """Everything the fake AI tools received, oldest first."""
    return [r for r in _recordings if tool is None or r.tool == tool]


@router.delete("/recordings", status_code=status.HTTP_204_NO_CONTENT)
async def clear_recordings() -> None:
    _recordings.clear()
