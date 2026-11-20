"""Adding a pattern from a plain-language description, with the model's answers scripted."""

import pytest

from gateway.app.protected.assist import _PatternAnswer
from gateway.tests.conftest import Api
from gateway.tests.doubles import FakeLLM
from gateway.tests.protected.conftest import EMPLOYEE

pytestmark = pytest.mark.usefixtures("clean_stores")


async def _ask(api: Api, analyst: dict[str, str], request: str) -> dict[str, object]:
    response = await api.client.post(
        "/api/protected/patterns/assist", json={"request": request}, headers=analyst
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_nothing_is_added_when_the_model_declines(
    api: Api, analyst: dict[str, str], llm: FakeLLM
) -> None:
    llm.answers["_PatternAnswer"] = _PatternAnswer(
        understood=False,
        name="",
        regex="",
        data_type="",
        examples=[],
        near_misses=[],
        explanation="That is a single name: add it as a term.",
    )
    refused = await api.client.post(
        "/api/protected/patterns/assist", json={"request": "x" * 9}, headers=api.as_(EMPLOYEE)
    )
    declined = await _ask(api, analyst, "Protect the name Halcyon")

    assert refused.status_code == 403
    assert declined == {"added": [], "message": "That is a single name: add it as a term."}


async def test_a_pattern_that_cannot_be_used_is_sent_back_once_and_then_kept(
    api: Api, analyst: dict[str, str], llm: FakeLLM
) -> None:
    def answer(text: str) -> _PatternAnswer:
        fixed = "cannot be used" in text
        return _PatternAnswer(
            understood=True,
            name="Support ticket number",
            regex=r"\bTCK-\d{6}\b" if fixed else r"(?<=ticket )\d+",
            data_type="TICKET",
            examples=["TCK-123456"],
            near_misses=[],
            explanation="",
        )

    llm.answers["_PatternAnswer"] = answer
    added = await _ask(api, analyst, "Our tickets look like TCK-123456")
    patterns = (await api.client.get("/api/protected/patterns", headers=analyst)).json()

    assert added["added"] == ["Support ticket number"] and len(llm.asked) == 2
    assert r"\bTCK-\d{6}\b" in {pattern["regex"] for pattern in patterns}


@pytest.mark.parametrize(
    ("regex", "why"),
    [(r"\d+", "ordinary text"), (r"\bREF-\d{4}\b", "its own example")],
)
async def test_a_pattern_too_loose_or_wrong_about_its_examples_is_not_added(
    api: Api, analyst: dict[str, str], llm: FakeLLM, regex: str, why: str
) -> None:
    llm.answers["_PatternAnswer"] = _PatternAnswer(
        understood=True,
        name="Reference",
        regex=regex,
        data_type="REFERENCE",
        examples=["TCK-123456"],
        near_misses=[],
        explanation="",
    )
    refused = await _ask(api, analyst, "Our references")
    patterns = (await api.client.get("/api/protected/patterns", headers=analyst)).json()

    assert refused["added"] == [] and why in str(refused["message"])
    assert regex not in {pattern["regex"] for pattern in patterns}


ADDRESS = (
    r"(?i)(?:^|[^\pL\pN])(?:address|διε[ύυ]θυνσ(?:η|ης|ή))\s{0,3}(?:is|είναι|[:=])\s{0,3}"
    r"(?P<value>[^\n;]{5,100})"
)


async def test_a_value_known_by_its_label_is_masked_without_the_label(
    api: Api, analyst: dict[str, str], llm: FakeLLM
) -> None:
    llm.answers["_PatternAnswer"] = _PatternAnswer(
        understood=True,
        name="Postal address",
        regex=ADDRESS,
        data_type="ADDRESS",
        examples=["Address: Ermou 12, Athens", "Η διεύθυνση είναι Πατησίων 76, Αθήνα"],
        near_misses=["please update your address soon", "η διεύθυνση άλλαξε χθες"],
        explanation="",
    )
    added = await _ask(api, analyst, "Addresses after the word address or διεύθυνση")
    found = await api.client.post(
        "/api/protected/test", json={"text": "Διεύθυνση: Σόλωνος 9, Αθήνα"}, headers=analyst
    )

    assert added["added"] == ["Postal address"]
    assert (
        added["message"]
        == "Added “Postal address”: in “Address: Ermou 12, Athens” it masks “Ermou 12, Athens”."
    )
    assert found.json()["masked_text"].startswith("Διεύθυνση: <ADDRESS_1>")


async def test_a_pattern_that_catches_its_own_near_miss_is_not_added(
    api: Api, analyst: dict[str, str], llm: FakeLLM
) -> None:
    llm.answers["_PatternAnswer"] = _PatternAnswer(
        understood=True,
        name="Postal address",
        regex=r"(?i)address\s+(?P<value>[^\n;]{5,100})",
        data_type="ADDRESS",
        examples=["address 12 Ermou St"],
        near_misses=["please update your address before Friday"],
        explanation="",
    )
    refused = await _ask(api, analyst, "Addresses after the word address")
    assert refused["added"] == [] and "should leave alone" in str(refused["message"])


async def test_a_follow_up_carries_the_request_it_refines(
    api: Api, analyst: dict[str, str], llm: FakeLLM
) -> None:
    llm.answers["_PatternAnswer"] = _PatternAnswer(
        understood=False,
        name="",
        regex="",
        data_type="",
        examples=[],
        near_misses=[],
        explanation="No.",
    )
    earlier = {"request": "Hide addresses", "message": "An address has no shape of its own."}
    body = {"request": "Only after the word address", "previous": earlier}
    response = await api.client.post("/api/protected/patterns/assist", json=body, headers=analyst)

    assert response.status_code == 200
    assert "Earlier request: Hide addresses" in llm.texts[-1]
    assert "The admin now says: Only after the word address" in llm.texts[-1]
