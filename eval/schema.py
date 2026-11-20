"""Shape of a results file in `eval/results`, which the runner writes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Score(BaseModel):
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int


class TypeScore(Score):
    data_type: str


class TierScore(Score):
    tiers: str = Field(description="Cumulative: `T0`, `T0+T1`, `T0+T1+T2`, `T0+T1+T2+T3`")


class DetectionResult(BaseModel):
    layers: Literal["default", "default+demo"]
    overall: Score
    by_type: list[TypeScore]
    by_tier: list[TierScore]


class TechniqueRecall(BaseModel):
    technique: str
    samples: int
    recall_with_normalisation: float
    recall_without_normalisation: float


class EvasionResult(BaseModel):
    samples: int
    recall_with_normalisation: float
    recall_without_normalisation: float
    by_technique: list[TechniqueRecall]


class FingerprintScore(Score):
    embedder: str
    variant: Literal["verbatim", "partial", "paraphrased", "translated", "all"]


class CategoryScore(BaseModel):
    method: Literal["T2 exemplars", "T3"]
    layers: Literal["default", "default+demo"]
    accuracy: float
    samples: int


class InjectionScore(Score):
    layers: Literal["layer 1", "layer 1 + layer 2"]
    added_latency_ms_p50: float | None = None
    added_cost_per_1k_usd: float | None = None


class RehydrationResult(BaseModel):
    responses: int
    restored_exactly: float
    placeholder_survival: float
    upstream: Literal["echo", "live model"]


class LeakResult(BaseModel):
    requests_checked: int
    upstream_leaks: int
    tool_destination_leaks: int


class LatencyRow(BaseModel):
    tier: str
    p50_ms: float
    p95_ms: float
    samples: int


class AgentScenarioResult(BaseModel):
    scenario: str
    protection: Literal["off", "standard", "detailed"]
    flagged: bool
    side_effect_blocked: bool
    real_values_leaked: int


class Miss(BaseModel):
    """An honest example of an error. Datasets are synthetic, so the text can be shown."""

    dataset: str
    sample_id: str
    kind: Literal["false_negative", "false_positive"]
    data_type: str
    text: str
    note: str | None = None


class EvalResults(BaseModel):
    name: str
    started: datetime
    finished: datetime
    models: dict[str, str]
    split: str = Field(description="Which split the numbers are reported on")
    dataset_sizes: dict[str, int]
    detection: list[DetectionResult]
    evasion: EvasionResult | None
    fingerprint: list[FingerprintScore]
    category: list[CategoryScore]
    injection: list[InjectionScore]
    rehydration: list[RehydrationResult]
    leak: LeakResult | None
    latency: list[LatencyRow]
    cost_per_1k_prompts_usd: float
    agent_scenarios: list[AgentScenarioResult]
    misses: list[Miss]
    skipped: list[str] = Field(description="Metrics that could not run, each with the reason")
