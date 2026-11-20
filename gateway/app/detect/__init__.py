from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gateway.app.core.deps import Deps
from gateway.app.core.types import (
    CategoryFinding,
    ContextualDetection,
    LocalDetection,
    RowSource,
    Tier,
    Usage,
)
from gateway.app.detect import category
from gateway.app.detect.fingerprint import (
    FingerprintScores,
    chunks,
    reduce_placeholders,
    to_findings,
    token_count,
)
from gateway.app.detect.settings import DetectionSettings
from gateway.app.llm.client import LLMResult, Matrix

if TYPE_CHECKING:
    from gateway.app.protected import ProtectedData

log = logging.getLogger(__name__)

T2_FAILED = "Fingerprint matching failed"
T3_FAILED = "The category model did not answer in time"
_NO_FINDINGS = LocalDetection(findings=(), timings_ms={})


@dataclass(frozen=True, slots=True)
class _Scored:
    """T2's raw result for one text. `scores` is None for a text too short to judge, and
    when the embedding request failed."""

    scores: FingerprintScores | None
    usage: Usage
    elapsed_ms: float
    failed: bool = False


class DetectionService:
    """Implements `core.interfaces.Detector`."""

    def __init__(
        self,
        deps: Deps,
        protected: ProtectedData,
        *,
        sources: frozenset[RowSource] | None = None,
        settings: DetectionSettings | None = None,
    ) -> None:
        self._deps = deps
        self._protected = protected
        self._sources = sources
        self.settings = settings or DetectionSettings()

    def scoped(self, sources: Iterable[RowSource]) -> DetectionService:
        """A detector that only uses protected-data rows from the given layers."""
        return DetectionService(
            self._deps, self._protected, sources=frozenset(sources), settings=self.settings
        )

    async def detect_local(self, text: str, *, normalise: bool = True) -> LocalDetection:
        engine = await self._protected.local_engine(self._sources)
        # CPU-bound, so it runs off the event loop.
        return await asyncio.to_thread(engine.detect, text, normalise_text=normalise)

    async def fingerprint_scores(self, masked_text: str) -> tuple[FingerprintScores | None, Usage]:
        """The raw T2 similarities, before thresholds. None for a text too short to judge."""
        (scored,) = await self._score([masked_text])
        if scored.failed:
            raise RuntimeError(T2_FAILED)
        return scored.scores, scored.usage

    async def detect_contextual(
        self,
        masked_text: str,
        *,
        local: LocalDetection,
        force_t3: bool = False,
        use_model: bool = True,
    ) -> ContextualDetection:
        """`use_model=False` stops at T2 whatever it found: no call to the inline model."""
        (scored,) = await self._score([masked_text])
        return await self._conclude(
            masked_text, local, scored, force_t3=force_t3, use_model=use_model
        )

    async def detect_contextual_many(
        self, masked_texts: Sequence[str], *, use_model: bool = True
    ) -> list[ContextualDetection]:
        """As `detect_contextual` for each text, with the chunks of all of them embedded
        in one request. For bulk work such as importing logged prompts."""
        scored = await self._score(masked_texts)
        return [
            await self._conclude(text, _NO_FINDINGS, item, force_t3=False, use_model=use_model)
            for text, item in zip(masked_texts, scored, strict=True)
        ]

    async def _score(self, masked_texts: Sequence[str]) -> list[_Scored]:
        """T2 for every text that is long enough, behind a single embedding request."""
        started = time.perf_counter()
        index = self._protected.fingerprint_index(self._sources)
        pieces = [self._chunks(text) for text in masked_texts]
        flat = [chunk for text_chunks in pieces for chunk in text_chunks]
        matrix: Matrix | None = None
        usage = Usage()
        failed = False
        if flat and len(index):
            try:
                embedded = await self._deps.llm.embed(flat)
            except Exception as failure:
                log.warning("T2 failed: %s", type(failure).__name__)
                failed = True
            else:
                matrix, usage = embedded.value, embedded.usage
        judged = sum(1 for text_chunks in pieces if text_chunks)
        elapsed_ms = (time.perf_counter() - started) * 1000 / max(1, judged)
        results: list[_Scored] = []
        offset = 0
        for text_chunks in pieces:
            if not text_chunks:
                results.append(_Scored(None, Usage(), 0.0))
            elif failed:
                results.append(_Scored(None, Usage(), elapsed_ms, failed=True))
            elif matrix is None:
                results.append(_Scored(FingerprintScores(None, None), Usage(), elapsed_ms))
            else:
                rows = matrix[offset : offset + len(text_chunks)]
                offset += len(text_chunks)
                share = len(text_chunks) / len(flat)
                results.append(
                    _Scored(
                        index.scores(rows, self.settings.t2_neighbours),
                        Usage(
                            input_tokens=round(usage.input_tokens * share),
                            cost_usd=usage.cost_usd * share,
                        ),
                        elapsed_ms,
                    )
                )
        return results

    def _chunks(self, masked_text: str) -> list[str]:
        """The chunks to embed; none for a text too short to judge."""
        reduced = reduce_placeholders(masked_text)
        if token_count(reduced) < self.settings.t2_min_tokens:
            return []
        return chunks(reduced)

    async def _conclude(
        self,
        masked_text: str,
        local: LocalDetection,
        scored: _Scored,
        *,
        force_t3: bool,
        use_model: bool,
    ) -> ContextualDetection:
        """Turn T2's similarities into findings, and ask T3 when they are inconclusive."""
        timings: dict[Tier, float] = {}
        tiers_run: list[Tier] = []
        categories: list[CategoryFinding] = []
        usage = scored.usage
        error = T2_FAILED if scored.failed else None
        if scored.scores is not None or scored.failed:
            tiers_run.append(Tier.T2)
            timings[Tier.T2] = scored.elapsed_ms
        if scored.scores is not None:
            vote = scored.scores.exemplars
            found = to_findings(
                scored.scores,
                self.settings.t2_document_threshold,
                self.settings.exemplar_threshold(vote.category if vote else None),
            )
            categories = [found] if found is not None else []

        inconclusive = any(not found.conclusive for found in categories)
        if use_model and (inconclusive or force_t3):
            tiers_run.append(Tier.T3)
            started = time.perf_counter()
            try:
                verdict = await self._classify(masked_text, local)
            except Exception as failure:
                log.warning("T3 failed: %s", type(failure).__name__)
                error = T3_FAILED
            else:
                usage += verdict.usage
                confirmed = category.to_finding(verdict.value, self.settings.t3_min_confidence)
                # The model overrules a resemblance, and adds to a document that matched.
                if inconclusive:
                    categories = []
                if confirmed is not None and confirmed.category not in {
                    found.category for found in categories
                }:
                    categories.append(confirmed)
            timings[Tier.T3] = (time.perf_counter() - started) * 1000
        return ContextualDetection(
            categories=tuple(categories),
            timings_ms=timings,
            tiers_run=tuple(tiers_run),
            usage=usage,
            error=error,
        )

    async def _classify(
        self, masked_text: str, local: LocalDetection
    ) -> LLMResult[category.CategoryVerdict]:
        timeout = self._deps.settings.inline_timeout_s
        return await asyncio.wait_for(
            category.classify(
                self._deps.llm,
                reduce_placeholders(masked_text),
                local,
                timeout_s=timeout,
                max_chars=self.settings.t3_max_chars,
            ),
            timeout,
        )


async def build(deps: Deps, protected: ProtectedData) -> DetectionService:
    return DetectionService(deps, protected)
