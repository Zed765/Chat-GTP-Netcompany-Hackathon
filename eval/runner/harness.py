"""What the runner measures: the gateway's own services, behind the protocols it calls.

In the gateway container `live.py` fills a `Toolkit` with the real services. The tests
fill it with fakes, which is how the arithmetic is proved without any detector.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import uuid4

from eval.schema import Miss
from gateway.app.core.interfaces import InjectionDetector, PolicyService, Vault
from gateway.app.core.types import ContextualDetection, LocalDetection, Tier

Layers = Literal["default", "default+demo"]
MISSES_PER_KIND = 4
MISS_TEXT_CHARS = 400


class Detector(Protocol):
    async def detect_local(self, text: str, normalise: bool = True) -> LocalDetection: ...

    async def detect_contextual(
        self,
        masked_text: str,
        *,
        local: LocalDetection,
        force_t3: bool = False,
        use_model: bool = True,
    ) -> ContextualDetection: ...


@dataclass(frozen=True)
class Toolkit:
    """`detectors` holds only the layers this run can measure; the rest is skipped."""

    detectors: Mapping[Layers, Detector]
    vault: Vault
    injection: Mapping[str, InjectionDetector]
    policy: PolicyService
    models: dict[str, str]
    embedder_id: str
    # False when the detector cannot run without its normalisation step.
    normalisation_switch: bool = True

    @property
    def best_detector(self) -> Detector:
        """The detector with the most data behind it, for metrics reported once."""
        return self.detectors.get("default+demo") or self.detectors["default"]


@dataclass
class Notebook:
    """Collects what every metric adds to the results: misses, timings, cost and gaps."""

    misses: list[Miss] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    timings: dict[Tier, list[float]] = field(default_factory=dict)
    cost_usd: float = 0.0
    prompts_costed: int = 0
    _kinds: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def miss(
        self, dataset: str, sample_id: str, kind: str, data_type: str, text: str, note: str
    ) -> None:
        """Keep a few examples of each kind of error. The sets are synthetic, so text is fine."""
        key = (dataset, kind, data_type)
        self._kinds[key] = self._kinds.get(key, 0) + 1
        if self._kinds[key] <= MISSES_PER_KIND:
            shown = text[:MISS_TEXT_CHARS]
            self.misses.append(
                Miss(
                    dataset=dataset,
                    sample_id=sample_id,
                    kind="false_negative" if kind == "false_negative" else "false_positive",
                    data_type=data_type,
                    text=shown,
                    note=note,
                )
            )

    def time(self, timings_ms: Mapping[Tier, float]) -> None:
        for tier, elapsed in timings_ms.items():
            self.timings.setdefault(tier, []).append(elapsed)


def conversation() -> str:
    """A vault scope of its own for each sample, so placeholders never mix."""
    return f"eval-{uuid4().hex}"
