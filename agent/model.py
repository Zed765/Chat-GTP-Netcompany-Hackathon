"""The agent's model, reached through the gateway's Responses API."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseFailedEvent,
    ResponseInputParam,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
    ToolParam,
)


class ModelError(RuntimeError):
    """The model started a response and could not finish it."""


@dataclass(frozen=True)
class Delta:
    """A piece of the answer's text, as it streams in."""

    text: str


@dataclass(frozen=True)
class Output:
    """The finished response's output items, ready to be sent back as input."""

    items: list[dict[str, Any]]


class Model(Protocol):
    def respond(
        self, *, instructions: str, items: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Delta | Output]:
        """Text deltas while the model writes, then exactly one `Output`."""
        ...


class GatewayModel:
    """Stateless: the whole conversation is sent on every call and nothing is stored upstream."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def respond(
        self, *, instructions: str, items: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Delta | Output]:
        stream = await self._client.responses.create(
            model=self._model,
            instructions=instructions,
            input=cast(ResponseInputParam, items),
            tools=cast(list[ToolParam], tools),
            parallel_tool_calls=False,
            store=False,
            stream=True,
            # Nothing is stored upstream, so reasoning items must come back whole to be resent.
            reasoning={"effort": "low"},
            include=["reasoning.encrypted_content"],
        )
        finished: list[dict[str, Any]] = []
        async for event in stream:
            if isinstance(event, ResponseTextDeltaEvent):
                yield Delta(event.delta)
            elif isinstance(event, ResponseOutputItemDoneEvent):
                finished.append(event.item.model_dump(mode="json", exclude_none=True))
            elif isinstance(event, ResponseFailedEvent):
                error = event.response.error
                raise ModelError(error.message if error else "The model did not answer.")
        yield Output(finished)
