from pathlib import Path
from typing import Any

import pytest
from openai import APIConnectionError

from gateway.app.config import Settings
from gateway.app.discovery.classify import (
    SiteDescription,
    draft_tools,
    read_site_descriptions,
    risk_score,
)
from gateway.app.discovery.schemas import RiskFactors
from gateway.tests.doubles import FakeLLM, Reply

Described = dict[str, SiteDescription]


@pytest.fixture
def described(settings: Settings) -> Described:
    """The four sites the test settings describe: two AI services and two that are not."""
    return read_site_descriptions(settings.site_descriptions_path)


def model(verdicts: dict[str, dict[str, Any]]) -> FakeLLM:
    """A model that answers for the domains it is given and cannot be reached for the rest."""

    def answer(text: str) -> Reply:
        domain = text.splitlines()[0].removeprefix("Domain: ")
        return verdicts.get(domain) or APIConnectionError(request=None)  # type: ignore[arg-type]

    return FakeLLM(answers={"_Verdict": answer})


def _verdict(**changes: Any) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "is_ai_service": True,
        "category": "meeting assistant",
        "summary": "Records and summarises meetings.",
        "reason": "The description calls it an AI meeting assistant.",
        "trains_on_customer_data": None,
        "retention_days": 90,
        "data_residency": "EU",
        "enterprise_terms": None,
        "sso": True,
        "certifications": ["SOC 2"],
    }
    return verdict | changes


@pytest.mark.parametrize(
    ("factors", "score"),
    [
        (RiskFactors(), 5),
        (RiskFactors(trains_on_customer_data=True, retention_days=400, data_residency="US"), 5),
        (RiskFactors(trains_on_customer_data=False), 4),
        (RiskFactors(trains_on_customer_data=False, retention_days=30), 3),
        (RiskFactors(trains_on_customer_data=False, retention_days=0, enterprise_terms=True), 2),
        (
            RiskFactors(
                trains_on_customer_data=False,
                retention_days=0,
                enterprise_terms=True,
                data_residency="EU",
            ),
            1,
        ),
    ],
)
def test_risk_score_counts_open_questions(factors: RiskFactors, score: int) -> None:
    assert risk_score(factors) == score


async def test_model_verdict_becomes_a_draft_and_other_sites_are_left_out(
    described: Described,
) -> None:
    llm = model(
        {
            "notesly.example": _verdict(),
            "promptforge.example": _verdict(is_ai_service=False),
            "dailyherald.example": _verdict(is_ai_service=False),
            "parcelpost.example": _verdict(is_ai_service=False),
        }
    )
    [draft] = await draft_tools(llm, described)
    assert (draft.domain, draft.name, draft.category) == (
        "notesly.example",
        "Notesly AI",
        "meeting assistant",
    )
    assert draft.description == "Records and summarises meetings."
    assert draft.risk_factors == RiskFactors(
        retention_days=90, data_residency="EU", sso=True, certifications=["SOC 2"]
    )
    assert draft.note == (
        "Drafted by the model from the site's description. "
        "The description calls it an AI meeting assistant."
    )
    assert llm.texts[0].startswith("Domain: notesly.example\nTitle: Notesly AI - Meeting notes")
    assert len(llm.texts) == len(described)


async def test_a_site_whose_model_call_fails_gets_no_draft(described: Described) -> None:
    llm = model({"notesly.example": _verdict()})
    drafts = await draft_tools(llm, described)
    assert [draft.domain for draft in drafts] == ["notesly.example"]


def test_site_descriptions_file_is_optional(tmp_path: Path) -> None:
    assert read_site_descriptions(tmp_path / "absent.json") == {}
    present = tmp_path / "sites.json"
    present.write_text('{"Notesly.Example": {"title": "Notesly"}}', encoding="utf-8")
    assert read_site_descriptions(present) == {
        "notesly.example": SiteDescription(title="Notesly", description="")
    }
