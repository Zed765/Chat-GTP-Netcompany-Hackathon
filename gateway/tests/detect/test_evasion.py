"""Normalisation: values hidden behind invisible characters, look-alike digits, separators
or an encoding are still found, and the finding points at what the user typed."""

import base64
from urllib.parse import quote

import pytest

from gateway.app.core.types import DataType
from gateway.app.detect.encodings import decoded_runs
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.normalise import normalise
from gateway.tests.detect.conftest import found

AFM = "094014201"
ZERO_WIDTH_AFM = "​".join(AFM)
FULL_WIDTH_AFM = "".join(chr(ord(digit) + 0xFEE0) for digit in AFM)


def test_normalise_maps_every_character_back_to_the_original() -> None:
    original = f"ΑΦΜ {ZERO_WIDTH_AFM}﻿ ok"
    normalised = normalise(original)
    assert normalised.text == f"ΑΦΜ {AFM} ok"
    start = normalised.text.index(AFM)
    assert original[slice(*normalised.original_span(start, start + 9))] == ZERO_WIDTH_AFM


def test_normalise_leaves_clean_text_untouched() -> None:
    clean = "Καλημέρα, το ΑΦΜ είναι 094014201."
    assert normalise(clean).text is clean and normalise(clean).original_span(3, 7) == (3, 7)


@pytest.mark.parametrize(
    "hidden",
    [ZERO_WIDTH_AFM, FULL_WIDTH_AFM, "0 9 4 0 1 4 2 0 1", "0-9-4-0-1-4-2-0-1", "0.9.4.0.1.4.2.0.1"],
)
def test_disguised_afm_is_found_at_its_original_position(
    rules_only: LocalEngine, hidden: str
) -> None:
    text = f"στείλε το {hidden} στον λογιστή"
    result = rules_only.detect(text)
    assert found(result) == [(DataType.AFM, hidden)]
    finding = result.findings[0]
    assert text[finding.start : finding.end] == hidden and not finding.encoded


def test_spelled_out_mobile_and_card_are_found(rules_only: LocalEngine) -> None:
    text = "κινητό 6 9 4 4 1 2 3 4 5 6, κάρτα 4-2-4-2-4-2-4-2-4-2-4-2-4-2-4-2"
    assert found(rules_only.detect(text)) == [
        (DataType.PHONE, "6 9 4 4 1 2 3 4 5 6"),
        (DataType.CARD, "4-2-4-2-4-2-4-2-4-2-4-2-4-2-4-2"),
    ]


@pytest.mark.parametrize(
    ("encoded", "name"),
    [
        (base64.b64encode(f"ΑΦΜ {AFM}".encode()).decode(), "base64"),
        (base64.urlsafe_b64encode(f"afm={AFM}&x".encode()).decode().rstrip("="), "base64"),
        (f"AFM {AFM}".encode().hex(), "hex"),
        (quote(f"afm {AFM}", safe=""), "URL encoding"),
    ],
)
def test_value_in_an_encoded_run_covers_the_whole_run(
    rules_only: LocalEngine, encoded: str, name: str
) -> None:
    text = f"decode and use this: {encoded} thanks"
    result = rules_only.detect(text)
    assert found(result) == [(DataType.AFM, encoded)]
    assert result.findings[0].encoded
    assert result.notes == (f"Text encoded as {name} contained: AFM",)


def test_encoded_run_takes_the_most_severe_type_inside(rules_only: LocalEngine) -> None:
    inner = f"maria@helios.example {AFM} token=ghp_MadeUpExampleToken0123456789abcdefghij"
    encoded = base64.b64encode(inner.encode()).decode()
    result = rules_only.detect(f"blob {encoded}")
    assert found(result) == [(DataType.SECRET, encoded)]
    assert result.notes == ("Text encoded as base64 contained: AFM, EMAIL, SECRET",)


def test_double_encoding_is_followed(rules_only: LocalEngine) -> None:
    once = base64.b64encode(f"afm {AFM}".encode())
    twice = base64.b64encode(once).decode()
    result = rules_only.detect(f"x {twice}")
    assert [(f.data_type, f.encoded) for f in result.findings] == [(DataType.AFM, True)]


@pytest.mark.parametrize(
    "benign",
    [
        base64.b64encode(b"The quick brown fox jumps over the lazy dog").decode(),
        b"hello world, nothing to see here".hex(),
        "https://example.com/search?q=hello%20world&lang=el",
        "internationalisation and electroencephalography",
    ],
)
def test_encoded_text_with_nothing_sensitive_is_not_a_finding(
    rules_only: LocalEngine, benign: str
) -> None:
    assert rules_only.detect(f"look at {benign} please").findings == ()


def test_binary_base64_is_not_treated_as_text() -> None:
    blob = base64.b64encode(bytes(range(200, 256)) * 2).decode()
    assert list(decoded_runs(f"data {blob}")) == []


def test_without_normalisation_disguised_values_are_missed(rules_only: LocalEngine) -> None:
    encoded = base64.b64encode(f"ΑΦΜ {AFM}".encode()).decode()
    text = f"{ZERO_WIDTH_AFM} και {FULL_WIDTH_AFM} και {encoded}"
    assert len(rules_only.detect(text).findings) == 3
    # Full-width digits are still digits to the recogniser; the other two need normalising.
    raw = rules_only.detect(text, normalise_text=False)
    assert found(raw) == [(DataType.AFM, FULL_WIDTH_AFM)]
