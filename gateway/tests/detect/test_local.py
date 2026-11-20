"""T0 and T1 together, with the language models loaded."""

import statistics
import time

import pytest

from gateway.app.core.types import DataType, LocalDetection, Tier
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.names import is_misread_person
from gateway.app.detect.ner import language_segments
from gateway.app.detect.spans import Span
from gateway.app.detect.terms import TermMatcher
from gateway.app.detect.tokens import tokenise
from gateway.tests.detect.conftest import default_terms, found

SCENE_EN = (
    "Hi, please draft a polite reply to Maria Papadopoulou of Helios Shipping S.A. in Piraeus. "
    "Her AFM is 094014201 and the refund goes to IBAN GR16 0110 1250 0000 0001 2300 695. "
    "She can be reached at maria.p@helios.example or +30 694 412 3456. "
    "John Smith from Acme Corp is in copy."
)
SCENE_EL = (
    "Καλημέρα, γράψε μια ευγενική απάντηση στην κυρία Μαρία Παπαδοπούλου της Ήλιος Ναυτιλιακή. "
    "Το ΑΦΜ της είναι 094014201 και η επιστροφή πάει στο IBAN GR1601101250000000012300695. "
    "Μένει στην οδό Ερμού 15, 105 63 Αθήνα. Σε κοινοποίηση ο Γιώργος Νικολάου."
)
TYPICAL_PROMPTS = (SCENE_EN, SCENE_EL, SCENE_EN + "\n\n" + SCENE_EL)
BUDGET_MS = 150


def _types(result: LocalDetection) -> dict[str, list[str]]:
    by_type: dict[str, list[str]] = {}
    for finding in result.findings:
        by_type.setdefault(finding.data_type, []).append(finding.text)
    return by_type


def test_scene_one_in_english(engine: LocalEngine) -> None:
    by_type = _types(engine.detect(SCENE_EN))
    assert by_type[DataType.PERSON] == ["Maria Papadopoulou", "John Smith"]
    assert by_type[DataType.CLIENT] == ["Helios Shipping S.A."]
    assert by_type[DataType.AFM] == ["094014201"]
    assert by_type[DataType.IBAN] == ["GR16 0110 1250 0000 0001 2300 695"]
    assert by_type[DataType.EMAIL] == ["maria.p@helios.example"]
    assert by_type[DataType.PHONE] == ["+30 694 412 3456"]
    assert by_type[DataType.ORG] == ["Acme Corp"]
    assert "Piraeus" in by_type[DataType.LOCATION]


def test_scene_one_in_greek(engine: LocalEngine) -> None:
    by_type = _types(engine.detect(SCENE_EL))
    assert by_type[DataType.PERSON] == ["Μαρία Παπαδοπούλου", "Γιώργος Νικολάου"]
    assert by_type[DataType.CLIENT] == ["Ήλιος Ναυτιλιακή"]
    assert by_type[DataType.AFM] == ["094014201"]
    assert by_type[DataType.IBAN] == ["GR1601101250000000012300695"]
    assert by_type[DataType.ADDRESS] == ["οδό Ερμού 15, 105 63 Αθήνα"]


@pytest.mark.parametrize("text", [*TYPICAL_PROMPTS, "", "   ", "no findings here at all"])
def test_findings_are_sorted_disjoint_and_index_the_original(
    engine: LocalEngine, text: str
) -> None:
    result = engine.detect(text)
    cursor = 0
    for finding in result.findings:
        assert cursor <= finding.start < finding.end <= len(text)
        assert text[finding.start : finding.end] == finding.text
        assert 0.5 <= finding.score <= 1.0
        cursor = finding.end
    assert set(result.timings_ms) == {Tier.T0, Tier.T1}


def test_an_email_is_not_split_by_the_names_inside_it(engine: LocalEngine) -> None:
    result = engine.detect("write to papadopoulou@helios-shipping.example about Helios Shipping")
    assert found(result) == [
        (DataType.EMAIL, "papadopoulou@helios-shipping.example"),
        (DataType.CLIENT, "Helios Shipping"),
    ]


def test_a_connection_string_is_one_secret(engine: LocalEngine) -> None:
    text = "DATABASE_URL=postgresql://app:MadeUp-Pass-2026@db.internal.example:5432/orders"
    (finding,) = engine.detect(text).findings
    assert finding.data_type == DataType.SECRET and finding.text.startswith("postgresql://")


@pytest.mark.parametrize(
    "text",
    [
        "Write a Python function that parses a CSV file and uploads it to S3 with Docker.",
        "Fix this bug: TypeError: Cannot read properties of undefined in UserList.tsx",
        "Γράψε μου μια συνταγή για μουσακά με μελιτζάνες για έξι άτομα.",
        "What is the difference between REST and GraphQL?",
    ],
)
def test_everyday_prompts_have_no_people_or_organisations(engine: LocalEngine, text: str) -> None:
    types = {finding.data_type for finding in engine.detect(text).findings}
    assert not types & {DataType.PERSON, DataType.ORG, DataType.CLIENT, DataType.SECRET}


def test_addresses_in_both_languages(engine: LocalEngine) -> None:
    text = "Our office is at 15 Ermou Street. Στείλε το στη Λεωφ. Κηφισίας 124, 151 25 Μαρούσι."
    addresses = _types(engine.detect(text))[DataType.ADDRESS]
    assert addresses == ["15 Ermou Street", "Λεωφ. Κηφισίας 124, 151 25 Μαρούσι"]


def test_each_line_goes_to_the_model_of_its_script() -> None:
    text = "Hello there\nΚαλημέρα σας\nκαι πάλι\n12345\nBye now"
    segments = [
        (text[start:end].strip(), language) for start, end, language in language_segments(text)
    ]
    assert segments == [
        ("Hello there", "en"),
        ("Καλημέρα σας\nκαι πάλι\n12345", "el"),
        ("Bye now", "en"),
    ]


def test_local_detection_stays_within_budget(engine: LocalEngine) -> None:
    """T0 plus T1 under 150 ms at the 95th percentile for typical prompts."""
    for prompt in TYPICAL_PROMPTS:
        engine.detect(prompt)
    elapsed: list[float] = []
    for _ in range(20):
        for prompt in TYPICAL_PROMPTS:
            started = time.perf_counter()
            result = engine.detect(prompt)
            elapsed.append((time.perf_counter() - started) * 1000)
            assert sum(result.timings_ms.values()) <= elapsed[-1]
    p95 = statistics.quantiles(elapsed, n=20)[-1]
    assert p95 < BUDGET_MS, f"p95 was {p95:.1f} ms"


def test_departments_in_a_crm_line_are_not_people(engine: LocalEngine) -> None:
    lines = "\n".join(
        f"- [C0{number}] Helios Shipping S.A. | company | contact: Oliver Fairbanks | team {team}"
        for number, team in enumerate(
            ("HR", "Legal", "Finance", "Sales", "Engineering", "Customer Support")
        )
    )
    result = engine.detect(lines)
    assert {finding.text for finding in result.findings} == {
        "Helios Shipping S.A.",
        "Oliver Fairbanks",
    }


def test_a_company_with_a_legal_form_survives_a_longer_model_span(engine: LocalEngine) -> None:
    text = (
        "Summarise the call with Yannis Karellis (+30 692 263 1010) from Foxhollow Pharma GmbH; "
        "they want to move the date."
    )
    assert (DataType.ORG, "Foxhollow Pharma GmbH") in found(engine.detect(text))


def test_a_person_the_model_calls_an_organisation() -> None:
    gazetteer = TermMatcher(default_terms()).gazetteer
    text = "Fill the form: full name Ilias Xydakis, of Ilias Trading Emporiki"
    tokens = tokenise(text)

    def as_org(value: str) -> Span:
        start = text.index(value)
        return Span(DataType.ORG, start, start + len(value), Tier.T1, 0.6, "ner:en")

    assert is_misread_person(as_org("Ilias Xydakis"), tokens, gazetteer)
    assert not is_misread_person(as_org("Ilias Trading Emporiki"), tokens, gazetteer)
    assert not is_misread_person(as_org("Xydakis"), tokens, gazetteer)


def test_address_with_the_number_first_takes_postcode_city_and_country(
    engine: LocalEngine,
) -> None:
    text = "διεύθυνση 182 Tsimiski Street, 546 24 Thessaloniki, Greece. Ποσό: 14.750 €."
    assert _types(engine.detect(text))[DataType.ADDRESS] == [
        "182 Tsimiski Street, 546 24 Thessaloniki, Greece"
    ]
