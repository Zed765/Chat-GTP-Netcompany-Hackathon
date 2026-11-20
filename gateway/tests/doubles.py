"""Stand-ins for the models, so that no test calls OpenAI. Product code never imports this."""

import asyncio
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, cast

import numpy as np
from openai import AsyncOpenAI
from pydantic import BaseModel

from gateway.app.config import Settings
from gateway.app.core.types import Usage
from gateway.app.detect.settings import DetectionSettings
from gateway.app.llm.client import LLM, Effort, LLMResult, Matrix, normalise_rows

DIMENSIONS = 2048
NGRAM_SIZES = (3, 4, 5)
# Where the hash embedder separates a match from a look-alike. The product's own thresholds
# are tuned for the embedding model and mean nothing for these vectors.
HASH_THRESHOLDS = DetectionSettings(
    t2_document_threshold=0.55, t2_exemplar_threshold=0.27, t2_code_threshold=0.18
)

Reply = BaseModel | Mapping[str, Any] | Exception
Answer = Reply | Callable[[str], Reply]


def hash_embed(texts: Sequence[str]) -> Matrix:
    """Deterministic vectors from hashed character n-grams: texts that share wording are
    close, in Greek and in English. It cannot match a paraphrase or a translation."""
    matrix = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    for row, text in enumerate(texts):
        folded = " ".join(text.casefold().split())
        for size in NGRAM_SIZES:
            for start in range(len(folded) - size + 1):
                bucket = zlib.crc32(folded[start : start + size].encode())
                # The top bit picks the sign, which keeps colliding n-grams from adding up.
                matrix[row, bucket % DIMENSIONS] += 1.0 if bucket >> 31 else -1.0
    return normalise_rows(np.sign(matrix) * np.log1p(np.abs(matrix)))


class UnscriptedModelCallError(AssertionError):
    """A test caused a model call it did not script an answer for."""


class _NoClient:
    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"A test reached for the OpenAI client ({name})")


@dataclass(frozen=True)
class Asked:
    """One structured call, as the fake received it."""

    schema: str
    instructions: str
    text: str
    effort: Effort


class FakeLLM(LLM):
    """The gateway's model client with no model behind it.

    Embeddings come from `hash_embed`. A structured call is answered from `answers`, keyed
    by the name of the schema it asks for: a reply, or a function from the text of the call
    to a reply. A reply that is an exception is raised. A call with no answer scripted is
    recorded in `unscripted` and fails, so a test cannot pass on a guess.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        answers: Mapping[str, Answer] | None = None,
        *,
        completion: str | None = None,
        usage: Usage | None = None,
        delay_s: float = 0.0,
        embedding_error: Exception | None = None,
    ) -> None:
        super().__init__(settings or Settings(), client=cast(AsyncOpenAI, _NoClient()))
        self.answers: dict[str, Answer] = dict(answers or {})
        self.completion = completion
        self.asked: list[Asked] = []
        self.embedded: list[list[str]] = []
        self.unscripted: list[str] = []
        self._usage = usage or Usage()
        self._delay_s = delay_s
        self._embedding_error = embedding_error

    @property
    def texts(self) -> list[str]:
        """The text of every structured call, in order."""
        return [call.text for call in self.asked]

    def _unscripted(self, what: str) -> NoReturn:
        self.unscripted.append(what)
        raise UnscriptedModelCallError(f"No answer is scripted for {what}")

    async def embed(self, texts: Sequence[str]) -> LLMResult[Matrix]:
        self.embedded.append(list(texts))
        if self._embedding_error is not None:
            raise self._embedding_error
        return LLMResult(hash_embed(texts), Usage(input_tokens=len(texts)))

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
        if schema.__name__ not in self.answers:
            self._unscripted(schema.__name__)
        self.asked.append(Asked(schema.__name__, instructions, text, effort))
        await asyncio.sleep(self._delay_s)
        answer = self.answers[schema.__name__]
        reply = answer(text) if callable(answer) else answer
        if isinstance(reply, Exception):
            raise reply
        return LLMResult(schema.model_validate(reply), self._usage)

    async def complete(
        self,
        *,
        instructions: str,
        text: str,
        effort: Effort = "medium",
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> LLMResult[str]:
        if self.completion is None:
            self._unscripted("a completion")
        return LLMResult(self.completion, self._usage)
