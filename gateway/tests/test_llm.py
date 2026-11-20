"""The model client against a fake OpenAI SDK. The real API has not been called from here."""

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr

from gateway.app.config import Settings
from gateway.app.llm.client import LLM


class Verdict(BaseModel):
    category: str


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
        return SimpleNamespace(output_parsed=Verdict(category="CONTRACT"), usage=usage)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="Three teams.", usage=None)


class FakeEmbeddings:
    async def create(self, *, model: str, input: list[str]) -> Any:  # noqa: A002
        data = [SimpleNamespace(embedding=[3.0, 4.0]) for _ in input]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10 * len(input)))


class FakeOpenAI:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.embeddings = FakeEmbeddings()
        self.timeouts: list[float | None] = []
        self.retries: int | None = None

    def with_options(self, *, timeout: float | None, max_retries: int) -> "FakeOpenAI":
        self.timeouts.append(timeout)
        self.retries = max_retries
        return self


@pytest.fixture
def fake() -> FakeOpenAI:
    return FakeOpenAI()


@pytest.fixture
def llm(settings: Settings, fake: FakeOpenAI) -> LLM:
    return LLM(settings, client=cast(AsyncOpenAI, fake))


async def test_structured_passes_schema_effort_and_timeout_and_prices_usage(
    llm: LLM, fake: FakeOpenAI
) -> None:
    result = await llm.structured(
        instructions="Classify.", text="<PERSON_1> signs", schema=Verdict, timeout_s=2.0
    )
    (call,) = fake.responses.calls
    assert result.value.category == "CONTRACT" and fake.timeouts == [2.0] and fake.retries == 0
    assert call["text_format"] is Verdict and call["reasoning"] == {"effort": "none"}
    assert call["model"] == "gpt-6-luna" and call["store"] is False
    assert result.usage.cost_usd == pytest.approx(0.60)


async def test_embeddings_are_normalised_and_counted(llm: LLM) -> None:
    result = await llm.embed(["a", "b", "c"])
    assert llm.embedder_id == "openai:text-embedding-3-large"
    assert np.allclose(result.value, [[0.6, 0.8]] * 3) and result.usage.input_tokens == 30


async def test_complete_returns_text(llm: LLM) -> None:
    assert (await llm.complete(instructions="Answer.", text="How many?")).value == "Three teams."


def test_an_empty_base_url_falls_back_to_the_public_api(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compose passes `OPENAI_BASE_URL=` when none is configured; the SDK must not use it."""
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    unset = settings.model_copy(update={"openai_api_key": SecretStr("k"), "openai_base_url": ""})
    assert str(LLM(unset)._client.base_url) == "https://api.openai.com/v1/"
