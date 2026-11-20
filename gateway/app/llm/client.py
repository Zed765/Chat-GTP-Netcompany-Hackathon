"""The one place that calls OpenAI."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from openai import AsyncOpenAI
from pydantic import BaseModel

from gateway.app.config import Settings
from gateway.app.core.types import Usage

Effort = Literal["none", "low", "medium", "high"]
Matrix = NDArray[np.float32]

# USD per million tokens, as published on 14 November 2026.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5-mini": (0.25, 2.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}
EMBEDDING_BATCH = 256
OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class LLMResult[T]:
    value: T
    usage: Usage


def usage_for(model: str, input_tokens: int, output_tokens: int) -> Usage:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)


def normalise_rows(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.where(norms == 0.0, 1.0, norms)).astype(np.float32)


class LLM:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self._settings = settings
        # An explicit address: the SDK would otherwise read an empty OPENAI_BASE_URL.
        self._client = client or AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.openai_base_url or OPENAI_BASE_URL,
            max_retries=1,
        )

    @property
    def embedder_id(self) -> str:
        """Stored with every fingerprint, so a change of embedding model is noticed."""
        return f"openai:{self._settings.model_embedding}"

    def _bounded(self, timeout_s: float | None) -> AsyncOpenAI:
        """A call with a hard timeout is not retried: a retry would double the wait."""
        if timeout_s is None:
            return self._client
        return self._client.with_options(timeout=timeout_s, max_retries=0)

    async def embed(self, texts: Sequence[str]) -> LLMResult[Matrix]:
        """One L2-normalised row per text."""
        model = self._settings.model_embedding
        rows: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), EMBEDDING_BATCH):
            batch = list(texts[start : start + EMBEDDING_BATCH])
            response = await self._client.embeddings.create(model=model, input=batch)
            rows.extend(item.embedding for item in response.data)
            tokens += response.usage.prompt_tokens
        return LLMResult(
            normalise_rows(np.asarray(rows, dtype=np.float32)), usage_for(model, tokens, 0)
        )

    async def structured[T: BaseModel](
        self,
        *,
        instructions: str,
        text: str,
        schema: type[T],
        effort: Effort = "none",
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResult[T]:
        model = model or self._settings.model_inline
        response = await self._bounded(timeout_s).responses.parse(
            model=model,
            instructions=instructions,
            input=text,
            text_format=schema,
            reasoning={"effort": effort},
            store=False,
        )
        if response.output_parsed is None:
            raise ValueError("The model returned no structured output")
        usage = response.usage
        return LLMResult(
            response.output_parsed,
            usage_for(model, usage.input_tokens, usage.output_tokens) if usage else Usage(),
        )

    async def complete(
        self,
        *,
        instructions: str,
        text: str,
        effort: Effort = "medium",
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResult[str]:
        model = model or self._settings.model_inline
        response = await self._bounded(timeout_s).responses.create(
            model=model,
            instructions=instructions,
            input=text,
            reasoning={"effort": effort},
            store=False,
        )
        usage = response.usage
        return LLMResult(
            response.output_text,
            usage_for(model, usage.input_tokens, usage.output_tokens) if usage else Usage(),
        )
