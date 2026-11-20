"""T0 recognisers that need more than a regex: a checksum, a registry or a context word."""

import re
from collections.abc import Callable, Iterator

import phonenumbers

from gateway.app.core.textnorm import fold
from gateway.app.core.types import DataType, Tier
from gateway.app.detect.spans import Span
from gateway.app.detect.validators import (
    IBAN_LENGTHS,
    afm_is_valid,
    amka_is_valid,
    card_is_valid,
    iban_is_valid,
)

CONTEXT_WINDOW = 48
SCORE_WITH_CONTEXT = 0.95
SCORE_CHECKSUM_ONLY = 0.7
SCORE_STRONG_CHECKSUM = 0.85
SCORE_SPELLED_OUT = 0.6
MIN_IBAN_DIGIT_SHARE = 0.5
MIN_SPELLED_OUT_DIGITS = 9
DEFAULT_REGION = "GR"
# Number-like strings the phone matcher may reject before it gives up on a text of digits.
MAX_PHONE_TRIES = 500

_SEP = r"[ .\-]"
_NOT_IN_NUMBER = r"(?<![\d])(?<!\d[.,])"
_NOT_BEFORE_NUMBER = r"(?![\d])(?![.,]\d)"

_AFM = re.compile(
    rf"(?<![^\W_])(?:(?P<prefix>EL|GR)[ \-]?)?{_NOT_IN_NUMBER}"
    rf"(?P<digits>\d{{9}}){_NOT_BEFORE_NUMBER}"
)
# Three groups of three with one separator throughout, and not an amount of money.
_AFM_GROUPED = re.compile(
    rf"(?<!\d)(?<!\d{_SEP})\d{{3}}(?P<sep>{_SEP})\d{{3}}(?P=sep)\d{{3}}"
    rf"(?!{_SEP}?\d)(?![ ]?(?:€|EUR|ευρ))",
    re.IGNORECASE,
)
_PERSONAL_NUMBER = re.compile(r"(?<![^\W_])(?=\d{0,2}[A-Z])[A-Z0-9]{3}(\d{9})(?![^\W_])")
_AMKA = re.compile(rf"(?<![^\W_]){_NOT_IN_NUMBER}\d{{6}}[ \-]?\d{{5}}{_NOT_BEFORE_NUMBER}")
_CARD = re.compile(r"(?<![^\W_])(?<!\d[ \-])\d(?:[ \-]?\d){11,18}(?![ \-]?\d)")
_IBAN_PREFIX = re.compile(r"(?<![^\W_])([A-Za-z])[ .\-]?([A-Za-z])[ .\-]?\d[ .\-]?\d")
# An email is found from its at-sign outwards, over bounded lengths, so a long run of
# address characters with no at-sign costs nothing.
_AT = re.compile(r"@|\s?[\[(]at[\])]\s?", re.IGNORECASE)
_DOT = r"(?:\.|\s?[\[(]dot[\])]\s?)"
_DOMAIN = re.compile(
    rf"[\w\-]{{1,63}}(?:{_DOT}[\w\-]{{1,63}}){{0,10}}{_DOT}[^\W\d_]{{2,24}}(?![\w\-])",
    re.IGNORECASE,
)
MAX_LOCAL_PART = 64
# One Greek letter (cards before 2000), or two letters that exist in both alphabets.
_ID_CARD_OLD = re.compile(
    r"(?<![^\W_])(?:(?P<greek>[ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ]{2}|[Α-Ω])|[ABEZHIKMNOPTYX]{2})[ \-]?\d{6}(?![^\W_])"
)
_ID_CARD_CURRENT = re.compile(r"(?<![^\W_])[A-Z]{2}[ \-]?\d{7}(?![^\W_])")
_SPELLED_OUT = re.compile(
    rf"(?<!\d)(?<!\d[ .\-])\d(?P<sep>[ .\-])\d(?:(?P=sep)\d){{{MIN_SPELLED_OUT_DIGITS - 2},}}"
    r"(?![ .\-]?\d)"
)


def _context(*words: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![^\W_])(?:{'|'.join(words)})")


_AFM_CONTEXT = _context(
    r"α\.?φ\.?μ", "afm", r"a\.f\.m", "vat", "tin", r"tax\s?(?:id|number|no)", r"φορολογικ\w*"
)
_NOT_AFM_CONTEXT = _context(
    r"order\w*", r"παραγγελ\w*", r"invoice\w*", r"τιμολογ\w*", r"ticket\w*", r"tracking\w*",
    r"ref\w*", r"κωδικ\w*", r"αρ\.?\s?πρωτ\w*",
)  # fmt: skip
_AMKA_CONTEXT = _context(r"α\.?μ\.?κ\.?α", "amka", r"social security\w*", r"ασφαλισ\w*")
_CARD_CONTEXT = _context(
    r"card\w*", r"καρτ\w*", "visa", "mastercard", "amex", r"credit\w*", r"debit\w*", r"πιστωτικ\w*"
)
_ID_CONTEXT = _context(
    r"α\.?δ\.?τ", r"ταυτοτητ\w*", r"δελτιο\w*", r"id card\w*", r"identity card\w*",
    r"id (?:number|no)\w*", r"tautotita\w*", r"id(?![^\W_])",
)  # fmt: skip
_PHONE_CONTEXT = _context(
    r"τηλ\w*", r"κιν\w*", r"tel\w*", r"phone\w*", r"mobile\w*", r"call\w*", "fax", r"φαξ",
    r"whatsapp", r"viber",
)  # fmt: skip


def _has_context(text: str, start: int, pattern: re.Pattern[str]) -> bool:
    return bool(pattern.search(fold(text[max(0, start - CONTEXT_WINDOW) : start])))


def _digits(text: str) -> str:
    return "".join(char for char in text if char.isdigit())


def _span(data_type: str, start: int, end: int, score: float, recogniser: str) -> Span:
    return Span(data_type, start, end, Tier.T0, score, recogniser)


def _afm(text: str) -> Iterator[Span]:
    for match in _AFM.finditer(text):
        if not afm_is_valid(match["digits"]):
            continue
        known = match["prefix"] is not None or _has_context(text, match.start(), _AFM_CONTEXT)
        if not known and _has_context(text, match.start(), _NOT_AFM_CONTEXT):
            continue
        score = SCORE_WITH_CONTEXT if known else SCORE_CHECKSUM_ONLY
        yield _span(DataType.AFM, match.start(), match.end(), score, "afm")
    for match in _AFM_GROUPED.finditer(text):
        if not afm_is_valid(_digits(match.group())):
            continue
        known = _has_context(text, match.start(), _AFM_CONTEXT)
        if not known and _has_context(text, match.start(), _NOT_AFM_CONTEXT):
            continue
        score = SCORE_WITH_CONTEXT if known else SCORE_SPELLED_OUT
        yield _span(DataType.AFM, match.start(), match.end(), score, "afm")
    # The personal number on current identity cards is a three-character prefix plus the AFM.
    for match in _PERSONAL_NUMBER.finditer(text):
        if afm_is_valid(match.group(1)):
            yield _span(
                DataType.AFM, match.start(), match.end(), SCORE_STRONG_CHECKSUM, "personal_number"
            )


def _amka(text: str) -> Iterator[Span]:
    for match in _AMKA.finditer(text):
        if amka_is_valid(_digits(match.group())):
            known = _has_context(text, match.start(), _AMKA_CONTEXT)
            score = SCORE_WITH_CONTEXT if known else SCORE_STRONG_CHECKSUM
            yield _span(DataType.AMKA, match.start(), match.end(), score, "amka")


def _card(text: str) -> Iterator[Span]:
    for match in _CARD.finditer(text):
        if card_is_valid(_digits(match.group())):
            known = _has_context(text, match.start(), _CARD_CONTEXT)
            score = SCORE_WITH_CONTEXT if known else SCORE_STRONG_CHECKSUM
            yield _span(DataType.CARD, match.start(), match.end(), score, "card")


def _iban(text: str) -> Iterator[Span]:
    for match in _IBAN_PREFIX.finditer(text):
        length = IBAN_LENGTHS.get((match.group(1) + match.group(2)).upper())
        if length is None:
            continue
        # Read on until the country's length is reached, allowing one separator at a time.
        compact = [char for char in match.group() if char.isalnum()]
        end = match.end()
        while len(compact) < length and end < len(text):
            if text[end] in " -." and end + 1 < len(text) and text[end + 1].isalnum():
                end += 1
            if not (text[end].isascii() and text[end].isalnum()):
                break
            compact.append(text[end])
            end += 1
        if end < len(text) and text[end].isalnum():
            continue
        iban = "".join(compact).upper()
        digit_share = sum(char.isdigit() for char in iban[4:]) / max(1, len(iban) - 4)
        if digit_share >= MIN_IBAN_DIGIT_SHARE and iban_is_valid(iban):
            yield _span(DataType.IBAN, match.start(), end, SCORE_WITH_CONTEXT, "iban")


def _local_part_start(text: str, end: int) -> int | None:
    """Where the part before the at-sign begins; None if there is none or it is too long."""
    start = end
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_.%+-"):
        start -= 1
        if end - start > MAX_LOCAL_PART:
            return None
    return start if start < end else None


def _email(text: str) -> Iterator[Span]:
    for at in _AT.finditer(text):
        start = _local_part_start(text, at.start())
        domain = _DOMAIN.match(text, at.end()) if start is not None else None
        if start is not None and domain is not None:
            yield _span(DataType.EMAIL, start, domain.end(), SCORE_WITH_CONTEXT, "email")


def _phone(text: str) -> Iterator[Span]:
    matcher = phonenumbers.PhoneNumberMatcher(
        text, DEFAULT_REGION, leniency=phonenumbers.Leniency.VALID, max_tries=MAX_PHONE_TRIES
    )
    for match in matcher:
        raw = match.raw_string
        international = raw.lstrip().startswith(("+", "00"))
        grouped = any(not char.isdigit() for char in raw.strip())
        mobile = phonenumbers.number_type(match.number) == phonenumbers.PhoneNumberType.MOBILE
        if international or _has_context(text, match.start, _PHONE_CONTEXT):
            score = SCORE_WITH_CONTEXT
        elif grouped or mobile:
            score = SCORE_CHECKSUM_ONLY
        else:
            # A bare run of digits in a valid landline range is as likely an order number.
            continue
        # The matcher keeps an opening bracket whose partner lies after the number.
        start = match.start + (raw.startswith("(") and ")" not in raw)
        yield _span(DataType.PHONE, start, match.end, score, "phone")


def _id_card(text: str) -> Iterator[Span]:
    for match in _ID_CARD_OLD.finditer(text):
        if _has_context(text, match.start(), _ID_CONTEXT):
            yield _span(DataType.ID_CARD, match.start(), match.end(), SCORE_WITH_CONTEXT, "id_card")
        elif match["greek"] and len(match["greek"]) == 2:
            yield _span(DataType.ID_CARD, match.start(), match.end(), SCORE_SPELLED_OUT, "id_card")
    for match in _ID_CARD_CURRENT.finditer(text):
        if _has_context(text, match.start(), _ID_CONTEXT):
            yield _span(DataType.ID_CARD, match.start(), match.end(), SCORE_WITH_CONTEXT, "id_card")


def _spelled_out(text: str) -> Iterator[Span]:
    """Digits typed one by one with a separator between each, a common way to dodge a filter."""
    for match in _SPELLED_OUT.finditer(text):
        digits = _digits(match.group())
        if afm_is_valid(digits):
            data_type, recogniser = DataType.AFM, "afm"
        elif amka_is_valid(digits):
            data_type, recogniser = DataType.AMKA, "amka"
        elif card_is_valid(digits):
            data_type, recogniser = DataType.CARD, "card"
        elif _is_phone(digits):
            data_type, recogniser = DataType.PHONE, "phone"
        else:
            continue
        yield _span(data_type, match.start(), match.end(), SCORE_SPELLED_OUT, recogniser)


def _is_phone(digits: str) -> bool:
    try:
        number = phonenumbers.parse(digits, DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return False
    return phonenumbers.is_valid_number(number)


RECOGNISERS: tuple[Callable[[str], Iterator[Span]], ...] = (
    _afm,
    _amka,
    _card,
    _iban,
    _email,
    _phone,
    _id_card,
    _spelled_out,
)


def find_identifiers(text: str) -> list[Span]:
    return [span for recognise in RECOGNISERS for span in recognise(text)]
