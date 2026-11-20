"""Server-sent events, read from upstream and written to the caller."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

DONE = "[DONE]"


@dataclass(frozen=True)
class ServerEvent:
    data: str
    event: str | None = None

    def json(self) -> dict[str, Any]:
        loaded = json.loads(self.data)
        if not isinstance(loaded, dict):
            raise ValueError("Expected a JSON object in a server-sent event")
        return loaded

    def encode(self) -> str:
        head = f"event: {self.event}\n" if self.event else ""
        return f"{head}data: {self.data}\n\n"


def encode(payload: dict[str, Any], event: str | None = None) -> str:
    return ServerEvent(json.dumps(payload, ensure_ascii=False), event).encode()


async def parse(lines: AsyncIterator[str]) -> AsyncIterator[ServerEvent]:
    """Group the lines of an event stream into events. Comments and unknown fields are dropped."""
    event: str | None = None
    data: list[str] = []
    async for line in lines:
        if not line:
            if data:
                yield ServerEvent("\n".join(data), event)
            event, data = None, []
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif line.startswith("event:"):
            event = line[6:].strip()
    if data:
        yield ServerEvent("\n".join(data), event)
