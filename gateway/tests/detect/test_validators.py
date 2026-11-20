"""Known-valid and known-invalid values for each checksum. The valid ones are published
examples or official test numbers; `defaults/SOURCES.md` says where each comes from."""

import pytest

from gateway.app.detect.validators import (
    afm_is_valid,
    amka_is_valid,
    card_is_valid,
    iban_is_valid,
    luhn_is_valid,
)


@pytest.mark.parametrize("afm", ["094014201", "094259216", "094019245", "090000045"])
def test_afm_accepts_valid_numbers(afm: str) -> None:
    assert afm_is_valid(afm)


@pytest.mark.parametrize(
    "afm",
    [
        "094014202",  # wrong check digit
        "123456781",  # python-stdnum's invalid example
        "000000000",  # all zeros pass the arithmetic and are rejected by rule
        "09401420",  # too short
        "0940142011",  # too long
        "09401420A",
    ],
)
def test_afm_rejects_invalid_numbers(afm: str) -> None:
    assert not afm_is_valid(afm)


def test_amka_needs_a_date_and_a_luhn_digit() -> None:
    assert amka_is_valid("01013099997")  # python-stdnum's valid example
    assert not amka_is_valid("01013099999")  # Luhn fails
    assert not amka_is_valid("32013099995")  # day 32
    assert not amka_is_valid("01133099993")  # month 13
    assert not amka_is_valid("0101309999")


def test_amka_accepts_29_february_only_in_a_leap_year() -> None:
    leap = next(f"290200{tail:05d}" for tail in range(100000) if luhn_is_valid(f"290200{tail:05d}"))
    common = next(
        f"290201{tail:05d}" for tail in range(100000) if luhn_is_valid(f"290201{tail:05d}")
    )
    assert amka_is_valid(leap) and not amka_is_valid(common)


@pytest.mark.parametrize(
    "iban",
    [
        "GR1601101250000000012300695",  # the SWIFT registry's example for Greece
        "GB82WEST12345698765432",
        "DE89370400440532013000",
        "FR1420041010050500013M02606",
        "CY17002001280000001200527600",
        "NL91ABNA0417164300",
    ],
)
def test_iban_accepts_registry_examples(iban: str) -> None:
    assert iban_is_valid(iban)


@pytest.mark.parametrize(
    "iban",
    [
        "GR1601101250000000012300696",  # mod 97 fails
        "GR160110125000000001230069",  # too short for Greece
        "GR16011012500000000123006AB",  # Greek account numbers are numeric
        "ZZ1601101250000000012300695",  # no such country
        "GB82WEST12345698765433",
    ],
)
def test_iban_rejects_invalid_numbers(iban: str) -> None:
    assert not iban_is_valid(iban)


@pytest.mark.parametrize(
    "card",
    [
        "4242424242424242",  # Visa test card
        "5555555555554444",  # Mastercard
        "2223003122003222",  # Mastercard 2-series
        "378282246310005",  # American Express
        "6011111111111117",  # Discover
        "3530111333300000",  # JCB
    ],
)
def test_card_accepts_test_numbers(card: str) -> None:
    assert card_is_valid(card)


@pytest.mark.parametrize(
    "card",
    [
        "4242424242424241",  # Luhn fails
        "1234567812345670",  # passes Luhn, no issuer starts with 1
        "42424242424242",  # Visa does not issue 14 digits
    ],
)
def test_card_rejects_invalid_numbers(card: str) -> None:
    assert not card_is_valid(card)
