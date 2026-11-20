from pathlib import Path

import pytest

from gateway.app.core.types import DataType, RowSource, Store
from gateway.app.detect.entropy import find_high_entropy, shannon_entropy
from gateway.app.detect.patterns import PatternError, PatternMatcher, PatternRule, compile_pattern
from gateway.app.protected.pack import PatternEntry, load_pattern_pack

DEFAULTS = Path(__file__).resolve().parents[3] / "defaults"
ENTRIES = [entry for group in load_pattern_pack(DEFAULTS)[0].groups for entry in group.patterns]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry.name)
def test_default_pattern_matches_its_example_and_not_its_near_miss(entry: PatternEntry) -> None:
    compiled = compile_pattern(entry.regex)
    assert compiled.search(entry.must_match), "must_match was not found"
    assert not compiled.search(entry.must_not_match), "must_not_match was found"


def test_default_pattern_names_are_unique() -> None:
    names = [entry.name for entry in ENTRIES]
    assert len(names) == len(set(names)) >= 40


@pytest.mark.parametrize("regex", [r"(?<=key=)\w+", r"(a)\1", r"(unclosed", r"a{2,1}"])
def test_only_re2_syntax_is_accepted(regex: str) -> None:
    with pytest.raises(PatternError, match="RE2"):
        compile_pattern(regex)


def test_a_pattern_that_matches_empty_text_is_rejected() -> None:
    with pytest.raises(PatternError, match="empty"):
        compile_pattern(r"\d*")


def test_matcher_reports_the_row_and_masks_only_the_value_group() -> None:
    rules = [
        PatternRule("row-1", "badge", r"\bBDG-[0-9]{6}\b", "BADGE", RowSource.UPLOADED, "custom"),
        PatternRule(
            "row-2",
            "door-code",
            r"door code: (?P<value>[0-9]{4})",
            "SECRET",
            RowSource.DEFAULT,
            "x",
        ),
    ]
    text = "Κάρτα BDG-004211, door code: 9931."
    spans = sorted(PatternMatcher(rules).find(text), key=lambda span: span.start)
    assert [(span.data_type, text[span.start : span.end]) for span in spans] == [
        ("BADGE", "BDG-004211"),
        ("SECRET", "9931"),
    ]
    assert spans[0].match is not None
    assert (spans[0].match.store, spans[0].match.row_id, spans[0].match.source) == (
        Store.PATTERNS,
        "row-1",
        RowSource.UPLOADED,
    )
    assert spans[0].recogniser == "pattern:badge"


def test_matcher_with_no_rules_finds_nothing() -> None:
    assert PatternMatcher([]).find("anything") == []


def _secrets(text: str) -> list[str]:
    return [text[span.start : span.end] for span in find_high_entropy(text)]


def test_entropy_separates_random_from_readable() -> None:
    assert shannon_entropy("aaaaaaaaaaaa") == 0.0
    assert shannon_entropy("q7Zp2LmX9vRt4KbN") > 3.5 > shannon_entropy("correcthorse")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("DB_PASSWORD=Tr0ub4dor&3", "Tr0ub4dor&3"),
        ('password: "hunter2 is mine"', "hunter2 is mine"),
        ("api_key = q7Zp2LmX9vRt4KbN", "q7Zp2LmX9vRt4KbN"),
        ("κωδικός: Kalimera2026!", "Kalimera2026!"),
        (
            "use q7Zp2LmX9vRt4KbNw8Yc3Hd6Jf5Gs1Ae0Uo for the build",
            "q7Zp2LmX9vRt4KbNw8Yc3Hd6Jf5Gs1Ae0Uo",
        ),
    ],
)
def test_entropy_check_finds_unformatted_secrets(text: str, secret: str) -> None:
    assert _secrets(text) == [secret]


@pytest.mark.parametrize(
    "text",
    [
        "password: required",
        "password = os.environ['DB_PASSWORD']",
        "api_key = ${API_KEY}",
        "token: <your token here>",
        "max_tokens = 4096 and token_count = 123456",
        "commit 3f786850e387550fdab836ed7e6dc881de23001b fixed it",
        "see https://example.com/files/q7Zp2LmX9vRt4KbNw8Yc3Hd6Jf5Gs1Ae0Uo for details",
        "the author: Shakespeare wrote Hamlet",
    ],
)
def test_entropy_check_leaves_ordinary_text_alone(text: str) -> None:
    assert _secrets(text) == []


def test_default_patterns_are_all_secrets() -> None:
    pack, version = load_pattern_pack(DEFAULTS)
    assert version.startswith(pack.pack_version + "+")
    assert {
        entry.data_type or group.data_type for group in pack.groups for entry in group.patterns
    } == {
        DataType.SECRET, DataType.PERSON, "STUDENT_ID", "GRADE", "PASSWORD", "USERNAME",
        "DATE_OF_BIRTH", "PASSPORT", "LICENSE_PLATE", "SALARY", "BANK_ACCOUNT", "IP_ADDRESS",
        "CARD_SECURITY", "INSURANCE_NUMBER", "DRIVING_LICENCE",
    }  # fmt: skip
