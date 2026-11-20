"""Checksum validators for the identifiers T0 recognises. Sources are in `defaults/SOURCES.md`."""

from datetime import date

AFM_WEIGHTS = (256, 128, 64, 32, 16, 8, 4, 2)

# IBAN length per country, from the SWIFT IBAN registry.
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22,
    "BI": 27, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DJ": 27,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HN": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28,
    "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "LY": 25, "MC": 27, "MD": 24, "ME": 22,
    "MK": 19, "MN": 20, "MR": 27, "MT": 31, "MU": 30, "NI": 28, "NL": 18, "NO": 15, "OM": 23,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "RU": 33, "SA": 24,
    "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "SO": 23, "ST": 25, "SV": 28,
    "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}  # fmt: skip

# Issuer prefixes and the lengths each issues, from the networks' published BIN ranges.
_CARD_RANGES: tuple[tuple[int, int, int, frozenset[int]], ...] = (
    (4, 4, 1, frozenset({13, 16, 19})),  # Visa
    (51, 55, 2, frozenset({16})),  # Mastercard
    (2221, 2720, 4, frozenset({16})),  # Mastercard 2-series
    (34, 34, 2, frozenset({15})),  # American Express
    (37, 37, 2, frozenset({15})),
    (36, 36, 2, frozenset({14})),  # Diners Club
    (300, 305, 3, frozenset({14})),
    (6011, 6011, 4, frozenset({16, 19})),  # Discover
    (644, 649, 3, frozenset({16, 19})),
    (65, 65, 2, frozenset({16, 19})),
    (3528, 3589, 4, frozenset({16, 17, 18, 19})),  # JCB
    (62, 62, 2, frozenset({16, 17, 18, 19})),  # UnionPay
    (50, 50, 2, frozenset({12, 13, 14, 15, 16, 17, 18, 19})),  # Maestro
    (56, 58, 2, frozenset({12, 13, 14, 15, 16, 17, 18, 19})),
    (67, 67, 2, frozenset({12, 13, 14, 15, 16, 17, 18, 19})),
)


def luhn_is_valid(digits: str) -> bool:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def afm_is_valid(digits: str) -> bool:
    """Greek tax number: nine digits, the last a mod-11 check over the first eight."""
    if len(digits) != 9 or not digits.isdigit() or digits == "000000000":
        return False
    total = sum(int(digit) * weight for digit, weight in zip(digits, AFM_WEIGHTS, strict=False))
    return total % 11 % 10 == int(digits[8])


def amka_is_valid(digits: str) -> bool:
    """Greek social security number: DDMMYY date of birth, four digits and a Luhn check digit."""
    if len(digits) != 11 or not digits.isdigit():
        return False
    day, month, year = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    try:
        # The century is not encoded. 20YY is a leap year whenever 19YY is, so it accepts both.
        date(2000 + year, month, day)
    except ValueError:
        return False
    return luhn_is_valid(digits)


def iban_is_valid(iban: str) -> bool:
    """`iban` is compact and upper-case. Checks the country's length and ISO 7064 mod 97-10."""
    if len(iban) != IBAN_LENGTHS.get(iban[:2], 0) or not iban.isalnum() or not iban.isascii():
        return False
    if not iban[2:4].isdigit():
        return False
    if iban[:2] == "GR" and not iban[4:].isdigit():
        return False
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def card_is_valid(digits: str) -> bool:
    """A known issuer prefix, a length that issuer uses, and a Luhn check digit."""
    if not digits.isdigit() or not any(
        low <= int(digits[:width]) <= high and len(digits) in lengths
        for low, high, width, lengths in _CARD_RANGES
    ):
        return False
    return luhn_is_valid(digits)
