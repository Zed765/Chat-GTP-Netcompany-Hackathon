"""A stand-in for the OpenAI client of the fake AI tools, so that no test calls OpenAI."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from mock_upstream.chat import openai_client
from mock_upstream.main import app

OPENING = "Here is a draft: "


class FakeOpenAI:
    """Answers with the last message it was sent, behind a fixed opening, so that every
    placeholder in a prompt comes back in the answer."""

    def __init__(self) -> None:
        self.responses = self
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return SimpleNamespace(output_text=OPENING + request["input"][-1]["content"])


@contextmanager
def fake_model() -> Iterator[FakeOpenAI]:
    """Puts a `FakeOpenAI` behind the fake AI tools for as long as the block runs."""
    fake = FakeOpenAI()
    app.dependency_overrides[openai_client] = lambda: fake
    try:
        yield fake
    finally:
        del app.dependency_overrides[openai_client]
