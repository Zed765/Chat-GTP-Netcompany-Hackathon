"""Tunable detection settings. The evaluation picks the thresholds on its training splits;
each can be overridden from the environment, for example `ASPIDA_T2_DOCUMENT_THRESHOLD`."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway.app.core.types import DataType


class DetectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASPIDA_", extra="ignore")

    t2_min_tokens: int = 40
    t2_neighbours: int = 5
    # Cosine similarity a prompt chunk must reach against a chunk of a company document. A
    # match is conclusive, so the threshold sits above every look-alike in the training
    # split of `fingerprint.jsonl` (other documents built from the same clauses reach 0.68).
    # Verbatim and partial excerpts pass; most paraphrases and all translations do not.
    t2_document_threshold: float = 0.69
    # Mean similarity of the winning category among the nearest exemplars. On the training
    # splits, contract, financial, health and HR documents score 0.43 or more and ordinary
    # business emails less. Source code scores lower, so it has a threshold of its own.
    t2_exemplar_threshold: float = 0.42
    t2_code_threshold: float = 0.25
    t3_min_confidence: float = 0.5
    t3_max_chars: int = 6000

    def exemplar_threshold(self, category: str | None = None) -> float:
        if category == DataType.SOURCE_CODE:
            return self.t2_code_threshold
        return self.t2_exemplar_threshold
