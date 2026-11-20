"""The rows of the committed evaluation sets. `eval/README.md` documents every field."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from eval.runner.scoring import NAME_TYPES, Span

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
NAMES = ("dlp", "evasion", "injection", "fingerprint", "category", "agent_scenarios")
REPORTED_SPLIT = "test"


class Label(BaseModel):
    start: int
    end: int
    type: str
    text: str
    client: str | None = None
    turn: int = 0

    def span(self) -> Span:
        is_client = self.client is not None and self.type in NAME_TYPES
        return Span(self.start, self.end, self.type, is_client)


class DlpSample(BaseModel):
    id: str
    language: str
    group: str
    text: str
    labels: list[Label]
    categories: list[str]
    negative: bool


class EvasionSample(BaseModel):
    id: str
    technique: str
    turns: list[str]
    labels: list[Label]


class InjectionSample(BaseModel):
    id: str
    label: Literal["injection", "benign"]
    carrier: str
    technique: str
    text: str


class FingerprintSample(BaseModel):
    id: str
    variant: Literal["verbatim", "partial", "paraphrased", "translated", "negative"]
    source_document: str | None
    text: str


class CategorySample(BaseModel):
    id: str
    category: str
    text: str


class AgentScenario(BaseModel):
    id: str
    technique: str
    content: str
    tool: str
    destination: Literal["trusted", "untrusted"]
    side_effects: bool
    record: str
    values: list[str]


def load[T: BaseModel](name: str, model: type[T], directory: Path = DATASETS) -> list[T]:
    """The rows of one set that numbers are reported on: the held-out split where there is one."""
    lines = (directory / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    return [
        model.model_validate(r) for r in rows if r.get("split", REPORTED_SPLIT) == REPORTED_SPLIT
    ]


def sizes(directory: Path = DATASETS) -> dict[str, int]:
    return {
        name: len((directory / f"{name}.jsonl").read_text(encoding="utf-8").splitlines())
        for name in NAMES
    }
