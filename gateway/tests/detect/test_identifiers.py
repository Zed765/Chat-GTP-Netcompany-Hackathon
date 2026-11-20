import pytest

from gateway.app.core.types import DataType
from gateway.app.detect.identifiers import find_identifiers


def _found(text: str) -> list[tuple[str, str]]:
    spans = sorted(find_identifiers(text), key=lambda span: span.start)
    return [(span.data_type, text[span.start : span.end]) for span in spans]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Her AFM is 094014201.", [(DataType.AFM, "094014201")]),
        ("ΑΦΜ: 094014201, ΔΟΥ Πειραιά", [(DataType.AFM, "094014201")]),
        ("VAT number EL094014201", [(DataType.AFM, "EL094014201")]),
        ("Α.Φ.Μ. 094 014 201", [(DataType.AFM, "094 014 201")]),
        ("ΑΦΜ 094014201 και 094019245", [(DataType.AFM, "094014201"), (DataType.AFM, "094019245")]),
        ("Προσωπικός αριθμός A12094014201", [(DataType.AFM, "A12094014201")]),
        ("ΑΜΚΑ 01013099997", [(DataType.AMKA, "01013099997")]),
        ("AMKA 010130-99997", [(DataType.AMKA, "010130-99997")]),
        (
            "IBAN GR16 0110 1250 0000 0001 2300 695 στην Εθνική",
            [(DataType.IBAN, "GR16 0110 1250 0000 0001 2300 695")],
        ),
        ("pay to GR1601101250000000012300695.", [(DataType.IBAN, "GR1601101250000000012300695")]),
        (
            "UK account GB82 WEST 1234 5698 7654 32",
            [(DataType.IBAN, "GB82 WEST 1234 5698 7654 32")],
        ),
        ("card 4242 4242 4242 4242 exp 12/27", [(DataType.CARD, "4242 4242 4242 4242")]),
        ("Amex 378282246310005", [(DataType.CARD, "378282246310005")]),
        ("mail maria.p@helios.example today", [(DataType.EMAIL, "maria.p@helios.example")]),
        (
            "write to maria [at] helios [dot] example",
            [(DataType.EMAIL, "maria [at] helios [dot] example")],
        ),
        ("τηλ. 210 123 4567", [(DataType.PHONE, "210 123 4567")]),
        ("κινητό 6944123456", [(DataType.PHONE, "6944123456")]),
        ("call +30 694 412 3456", [(DataType.PHONE, "+30 694 412 3456")]),
        ("London office +44 20 7946 0958", [(DataType.PHONE, "+44 20 7946 0958")]),
        ("ΑΔΤ ΑΒ 123456", [(DataType.ID_CARD, "ΑΒ 123456")]),
        ("αριθμός ταυτότητας Χ 123456", [(DataType.ID_CARD, "Χ 123456")]),
        ("identity card AK1234567", [(DataType.ID_CARD, "AK1234567")]),
        ("full name, ΑΜΚΑ, ID HH7959582, mobile", [(DataType.ID_CARD, "HH7959582")]),
    ],
)
def test_identifier_is_found(text: str, expected: list[tuple[str, str]]) -> None:
    assert _found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Order 123456789 has shipped",  # nine digits, checksum fails
        "Αρ. παραγγελίας 094014201",  # valid checksum, but called an order number
        "Invoice ref 094014201",
        "total 1094014201.50 EUR",  # part of a longer number
        "ΑΜΚΑ 01013099999",  # Luhn fails
        "IBAN GR16 0110 1250 0000 0001 2300 696",  # mod 97 fails
        "is 30 people in the room today and tomorrow",  # shaped like an Icelandic IBAN
        "card 4242 4242 4242 4241",
        "tracking 1234567812345670",  # passes Luhn, no issuer
        "ticket 2101234567",  # a bare number in a landline range
        "part AB123456 in stock",  # shaped like an identity card, no context
        "version 1.2.3.4.5.6.7.8.9",
        "user@localhost",
    ],
)
def test_look_alike_is_left_alone(text: str) -> None:
    assert _found(text) == []


def test_context_raises_the_score() -> None:
    with_context = find_identifiers("ΑΦΜ 094014201")[0]
    without = find_identifiers("094014201")[0]
    assert with_context.score > without.score >= 0.5


@pytest.mark.parametrize("written", ["094 014 201", "094.014.201", "094-014-201"])
def test_grouped_afm_is_found_without_a_context_word(written: str) -> None:
    (span,) = find_identifiers(f"Client detail: {written}. Please check it.")
    assert span.data_type == DataType.AFM and span.score < 0.7


@pytest.mark.parametrize(
    "text",
    [
        "the budget is 094.014.201 € this year",  # an amount of money
        "the budget is 094.014.201 ευρώ",
        "code 094 014.201",  # two different separators
        "order 094 014 201",  # called an order number
    ],
)
def test_grouped_digits_that_are_not_an_afm(text: str) -> None:
    assert _found(text) == []


def test_iban_typed_with_a_dot_between_every_character() -> None:
    dotted = ".".join("GR1601101250000000012300695")
    assert _found(f"The value is {dotted}. Is it right?") == [(DataType.IBAN, dotted)]


def test_phone_span_leaves_an_unmatched_bracket_out() -> None:
    assert _found("Yannis (+30 694 412 3456) called") == [(DataType.PHONE, "+30 694 412 3456")]
    assert _found("call (210) 123 4567 now") == [(DataType.PHONE, "(210) 123 4567")]
