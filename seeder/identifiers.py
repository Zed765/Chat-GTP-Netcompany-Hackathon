"""Generators and validators for the identifiers the demo data carries.

Every generated value passes its checksum, so the gateway's validators accept it. The
validators here exist to test the generators; the gateway has its own.
"""

from datetime import date
from random import Random

AFM_WEIGHTS = (256, 128, 64, 32, 16, 8, 4, 2)
IBAN_LENGTH = 27
# Letters that look the same in the Greek and Latin alphabets, as the current ID card uses.
ID_CARD_LETTERS = "ABEZHIKMNOPTYX"
OLD_ID_CARD_LETTERS = "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"


def _digits(rng: Random, count: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(count))


def afm_check_digit(first_eight: str) -> int:
    total = sum(int(digit) * weight for digit, weight in zip(first_eight, AFM_WEIGHTS, strict=True))
    return total % 11 % 10


def is_valid_afm(value: str) -> bool:
    if len(value) != 9 or not value.isdecimal() or value == "0" * 9:
        return False
    return afm_check_digit(value[:8]) == int(value[8])


def make_afm(rng: Random) -> str:
    first_eight = _digits(rng, 8)
    while first_eight == "0" * 8:
        first_eight = _digits(rng, 8)
    return f"{first_eight}{afm_check_digit(first_eight)}"


def make_invalid_afm(rng: Random) -> str:
    """Nine digits whose check digit is wrong: a hard negative."""
    valid = make_afm(rng)
    return f"{valid[:8]}{(int(valid[8]) + rng.randrange(1, 10)) % 10}"


def luhn_is_valid(number: str) -> bool:
    if not number.isdecimal():
        return False
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def luhn_check_digit(payload: str) -> int:
    return next(digit for digit in range(10) if luhn_is_valid(f"{payload}{digit}"))


def is_valid_amka(value: str) -> bool:
    if len(value) != 11 or not value.isdecimal() or not luhn_is_valid(value):
        return False
    day, month, year = int(value[:2]), int(value[2:4]), int(value[4:6])
    # The century is not encoded, so a date that exists in either century is accepted.
    for century in (1900, 2000):
        try:
            date(century + year, month, day)
        except ValueError:
            continue
        return True
    return False


def random_birth_date(rng: Random) -> date:
    return date.fromordinal(
        rng.randrange(date(1950, 1, 1).toordinal(), date(2004, 1, 1).toordinal())
    )


def make_amka(rng: Random, born: date | None = None) -> str:
    payload = f"{born or random_birth_date(rng):%d%m%y}{_digits(rng, 4)}"
    return f"{payload}{luhn_check_digit(payload)}"


def _mod97(value: str) -> int:
    return int("".join(str(int(char, 36)) for char in value)) % 97


def is_valid_iban(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    if len(compact) != IBAN_LENGTH or not compact.startswith("GR") or not compact[2:].isdecimal():
        return False
    return _mod97(compact[4:] + compact[:4]) == 1


def make_iban(rng: Random) -> str:
    """A Greek IBAN: bank (3), branch (4) and account (16) digits behind `GR` and two check digits.

    Bank codes start with 9, which no Greek bank uses, so no real account can be hit.
    """
    bban = f"9{_digits(rng, 2)}{_digits(rng, 4)}{_digits(rng, 16)}"
    check = 98 - _mod97(f"{bban}GR00")
    return f"GR{check:02d}{bban}"


def spaced_iban(iban: str) -> str:
    """The printed form, in groups of four."""
    return " ".join(iban[index : index + 4] for index in range(0, len(iban), 4))


def make_card(rng: Random) -> str:
    prefix = rng.choice(("4", "51", "52", "53", "54", "55"))
    payload = f"{prefix}{_digits(rng, 15 - len(prefix))}"
    return f"{payload}{luhn_check_digit(payload)}"


def make_id_card(rng: Random, *, current: bool) -> str:
    """Two letters and seven digits today; two Greek letters and six on older cards."""
    if current:
        return f"{''.join(rng.choices(ID_CARD_LETTERS, k=2))}{_digits(rng, 7)}"
    return f"{''.join(rng.choices(OLD_ID_CARD_LETTERS, k=2))} {_digits(rng, 6)}"


def make_mobile(rng: Random) -> str:
    return f"+30 69{rng.randrange(10)} {_digits(rng, 3)} {_digits(rng, 4)}"


def make_landline(rng: Random) -> str:
    return f"+30 21{rng.randrange(10)} {_digits(rng, 3)} {_digits(rng, 4)}"
