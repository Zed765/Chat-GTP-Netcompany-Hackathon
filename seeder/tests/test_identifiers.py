from random import Random

import pytest

from seeder import identifiers


@pytest.mark.parametrize("afm", ["094014201", "090000045", "094019245", "997073525"])
def test_known_valid_afms_pass(afm: str) -> None:
    assert identifiers.is_valid_afm(afm)


@pytest.mark.parametrize("afm", ["123456789", "000000000", "094014202", "09401420", "09401420A"])
def test_invalid_afms_fail(afm: str) -> None:
    assert not identifiers.is_valid_afm(afm)


def test_the_registry_example_iban_passes_and_a_changed_digit_fails() -> None:
    assert identifiers.is_valid_iban("GR1601101250000000012300695")
    assert identifiers.is_valid_iban("GR16 0110 1250 0000 0001 2300 695")
    assert not identifiers.is_valid_iban("GR1601101250000000012300696")
    assert not identifiers.is_valid_iban("DE89370400440532013000")


@pytest.mark.parametrize("number", ["79927398713", "4111111111111111", "5555555555554444"])
def test_luhn_accepts_reference_numbers(number: str) -> None:
    assert identifiers.luhn_is_valid(number)
    assert not identifiers.luhn_is_valid(number[:-1] + str((int(number[-1]) + 1) % 10))


def test_amka_needs_a_real_date_and_a_luhn_digit() -> None:
    payload = "0101801234"
    valid = f"{payload}{identifiers.luhn_check_digit(payload)}"
    assert identifiers.is_valid_amka(valid)
    assert not identifiers.is_valid_amka(valid[:-1] + str((int(valid[-1]) + 1) % 10))
    impossible = "3213801234"
    assert not identifiers.is_valid_amka(f"{impossible}{identifiers.luhn_check_digit(impossible)}")


def test_every_generated_identifier_validates() -> None:
    rng = Random(7)
    for _ in range(300):
        assert identifiers.is_valid_afm(identifiers.make_afm(rng))
        assert not identifiers.is_valid_afm(identifiers.make_invalid_afm(rng))
        iban = identifiers.make_iban(rng)
        assert identifiers.is_valid_iban(iban)
        assert identifiers.is_valid_iban(identifiers.spaced_iban(iban))
        assert identifiers.is_valid_amka(identifiers.make_amka(rng))
        card = identifiers.make_card(rng)
        assert len(card) == 16 and identifiers.luhn_is_valid(card)


def test_id_cards_follow_the_current_and_the_older_format() -> None:
    rng = Random(3)
    current = identifiers.make_id_card(rng, current=True)
    older = identifiers.make_id_card(rng, current=False)
    assert len(current) == 9 and current[:2].isalpha() and current[2:].isdecimal()
    letters, digits = older.split()
    assert len(letters) == 2 and len(digits) == 6 and digits.isdecimal()
