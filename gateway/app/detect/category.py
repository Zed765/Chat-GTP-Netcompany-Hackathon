"""T3: ask the inline model which document category a masked text belongs to."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from gateway.app.core.types import CategoryFinding, DataType, LocalDetection, Tier
from gateway.app.detect.fingerprint import describe
from gateway.app.llm.client import LLM, LLMResult

NO_CATEGORY = "NONE"

INSTRUCTIONS = """You classify text that an employee is about to send to an AI tool.
Personal and company identifiers were already replaced by placeholders such as <PERSON> or
<AFM_1>; treat a placeholder as the kind of value it names.

Choose the one category the text belongs to:
- CONTRACT: an agreement or part of one: clauses, parties, obligations, terms, signatures.
- FINANCIAL: financial statements, budgets, forecasts, invoices, payroll or pricing figures.
- HEALTH: medical records, diagnoses, treatment, test results, sick-leave details.
- HR: personnel matters: evaluations, salaries of named staff, disciplinary or hiring files.
- SOURCE_CODE: program source code or configuration, beyond a short generic snippet.
- CLIENT_CONFIDENTIAL: non-public information about a named client: deals, accounts, plans.
- NONE: everyday requests, public information, generic questions, anything else.

A question about a topic is NONE: asking how contracts work is not a contract.
The text may be Greek, English or both. Judge the content, not the language."""


class CategoryVerdict(BaseModel):
    category: Literal[
        "CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE", "CLIENT_CONFIDENTIAL", "NONE"
    ]
    confidence: float = Field(ge=0.0, le=1.0)


def _prompt(masked_text: str, local: LocalDetection, max_chars: int) -> str:
    counts = Counter(finding.data_type for finding in local.findings)
    found = ", ".join(f"{name} x{count}" for name, count in sorted(counts.items())) or "nothing"
    return f"Identifiers found in the text: {found}\n\nText:\n{masked_text[:max_chars]}"


async def classify(
    llm: LLM, masked_text: str, local: LocalDetection, *, timeout_s: float, max_chars: int
) -> LLMResult[CategoryVerdict]:
    return await llm.structured(
        instructions=INSTRUCTIONS,
        text=_prompt(masked_text, local, max_chars),
        schema=CategoryVerdict,
        effort="none",
        timeout_s=timeout_s,
    )


def to_finding(verdict: CategoryVerdict, min_confidence: float) -> CategoryFinding | None:
    if verdict.category == NO_CATEGORY or verdict.category not in DataType.CATEGORIES:
        return None
    return CategoryFinding(
        category=verdict.category,
        tier=Tier.T3,
        score=verdict.confidence,
        conclusive=verdict.confidence >= min_confidence,
        evidence=f"classified as {describe(verdict.category)}",
    )
