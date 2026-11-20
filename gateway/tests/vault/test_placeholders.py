import pytest

from gateway.app.vault.placeholders import (
    HOLD_BACK_CHARS,
    PLACEHOLDER_INSTRUCTION,
    SECRET_PLACEHOLDER,
    PlaceholderSpan,
    candidates,
    find_placeholders,
    held_back_from,
    lookup_key,
    make,
    parse,
)

KNOWN = lookup_key("<PERSON_1>")


@pytest.mark.parametrize(
    ("data_type", "number", "placeholder"),
    [
        ("PERSON", 1, "<PERSON_1>"),
        ("ID_CARD", 12, "<ID_CARD_12>"),
        ("PROJECT", 2, "<PROJECT_2>"),
        ("project code", 3, "<PROJECT_CODE_3>"),
        ("Έργο", 1, "<ΈΡΓΟ_1>"),
        ("2fa", 1, "<TYPE_2FA_1>"),
        ("???", 1, "<VALUE_1>"),
        ("A" * 60, 1, f"<{'A' * 24}_1>"),
    ],
)
def test_make_and_parse_agree(data_type: str, number: int, placeholder: str) -> None:
    assert make(data_type, number) == placeholder
    parsed = parse(placeholder)
    assert parsed is not None
    assert parsed == (placeholder[1:-1].rpartition("_")[0], number)


@pytest.mark.parametrize(
    "token", ["<person_1>", "<PERSON_1", "PERSON_1", "<PERSON>", "<_1>", "<PERSON_x>", "<h1>"]
)
def test_parse_accepts_only_the_exact_spelling(token: str) -> None:
    assert parse(token) is None


def test_the_secret_mark_is_not_a_numbered_placeholder() -> None:
    assert parse(SECRET_PLACEHOLDER) is None
    assert list(candidates(f"key {SECRET_PLACEHOLDER} here")) == []


def test_the_instruction_is_one_line_and_shows_the_format() -> None:
    assert "\n" not in PLACEHOLDER_INSTRUCTION
    assert make("PERSON", 1) in PLACEHOLDER_INSTRUCTION


@pytest.mark.parametrize(
    "mangled",
    [
        "<PERSON_1>",
        "<person_1>",
        "<Person_1>",
        "< PERSON_1 >",
        "<PERSON 1>",
        "<PERSON _ 1>",
        "<PERSON1>",
        r"\<PERSON_1\>",
        r"<PERSON\_1>",
        "&lt;PERSON_1&gt;",
        "&LT;person_1&GT;",
        "PERSON_1",
        "person_1",
        r"PERSON\_1",
        "<PERSON_1",
        "PERSON_1>",
    ],
)
def test_every_common_mangling_has_the_key_of_the_exact_placeholder(mangled: str) -> None:
    (candidate,) = candidates(f"Dear {mangled}, hello")
    assert candidate.key == KNOWN
    assert (candidate.start, candidate.end) == (5, 5 + len(mangled))


@pytest.mark.parametrize(
    "text",
    ["PERSON 1", "person1", "MY_PERSON_1x", "PERSON_1_draft", "xPERSON_1", "PERSON_", "<PERSON>"],
)
def test_text_that_is_not_a_placeholder_does_not_get_its_key(text: str) -> None:
    assert KNOWN not in {candidate.key for candidate in candidates(text)}


def test_a_backslash_before_an_unescaped_placeholder_is_the_users_own() -> None:
    text = r"C:\Users\<PERSON_1>\notes"
    (candidate,) = candidates(text)
    assert text[candidate.start : candidate.end] == "<PERSON_1>"


def test_find_placeholders_reports_types_and_exact_spelling() -> None:
    text = "Ask <PERSON_1> (< afm_2 >) about <SECRET_REDACTED>, <h1> and <CUSTOM_TYPE_3>."
    assert find_placeholders(text) == [
        PlaceholderSpan(4, 14, "<PERSON_1>", "PERSON"),
        PlaceholderSpan(16, 25, "<AFM_2>", "AFM"),
        PlaceholderSpan(33, 50, "<SECRET_REDACTED>", "SECRET"),
        PlaceholderSpan(61, 76, "<CUSTOM_TYPE_3>", "CUSTOM_TYPE"),
    ]


def test_find_placeholders_ignores_tokens_without_both_brackets() -> None:
    assert find_placeholders("PERSON_1, <PERSON_2 and UTF_8") == []


def _known(key: str) -> bool:
    return KNOWN.startswith(key)


@pytest.mark.parametrize(
    ("buffer", "held"),
    [
        ("Hello <", "<"),
        ("Hello <PER", "<PER"),
        ("Hello <PERSON_1", "<PERSON_1"),
        ("Hello < person 1 ", "< person 1 "),
        ("Hello &", "&"),
        ("Hello &l", "&l"),
        ("Hello &lt;PERSON_1&g", "&lt;PERSON_1&g"),
        ("Hello \\", "\\"),
        (r"Hello \<PERSON\_", r"\<PERSON\_"),
        ("Hello PERS", "PERS"),
        ("Hello PERSON_1", "PERSON_1"),
        ("Hello person_1&g", "person_1&g"),
        ("Hello <PERSON_1>", ""),
        ("Hello world", ""),
        ("Hello PERSON_1 ", ""),
        ("a < b, c", ""),
        ("Hello PERSONAL", ""),
    ],
)
def test_only_a_tail_that_could_become_a_placeholder_is_held_back(buffer: str, held: str) -> None:
    assert buffer[held_back_from(buffer, _known) :] == held


def test_a_tail_longer_than_any_placeholder_is_released() -> None:
    buffer = "<" + "a" * HOLD_BACK_CHARS
    assert held_back_from(buffer, _known) == len(buffer)
