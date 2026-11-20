"""The parts of the stores that need no database."""

import io
import time
import zlib

import pytest
from cryptography.exceptions import InvalidTag
from pypdf import PdfWriter

from gateway.app.core.types import DataType, Finding, Tier
from gateway.app.protected.crypto import TermCipher
from gateway.app.protected.documents import _blocks
from gateway.app.protected.errors import InvalidInputError, TooLargeError, UnsupportedFileError
from gateway.app.protected.extract import MAX_EXPANDED_BYTES, MAX_PDF_PAGES, extract_text
from gateway.app.protected.imports import document_category, parse_term_file, validate_rows
from gateway.app.protected.preview import mask_preview
from gateway.app.protected.term_source import terms_from_clients
from gateway.tests.protected.helpers import (
    CONTRACT,
    docx_bomb,
    docx_bytes,
    pdf_bytes,
    pdf_document,
)


def test_cipher_round_trips_and_never_repeats_itself() -> None:
    cipher = TermCipher(b"k" * 32)
    first, second = cipher.encrypt("Ζέφυρος Ναυτιλιακή"), cipher.encrypt("Ζέφυρος Ναυτιλιακή")
    assert first != second and "Ζέφυρος".encode() not in first
    assert cipher.decrypt(first) == cipher.decrypt(second) == "Ζέφυρος Ναυτιλιακή"
    assert cipher.decrypt_list(cipher.encrypt_list(["ZML", "Ζέφυρος"])) == ("ZML", "Ζέφυρος")
    assert cipher.decrypt_list(None) == ()
    with pytest.raises(InvalidTag):
        TermCipher(b"x" * 32).decrypt(first)


def test_lookup_key_ignores_case_accents_and_spacing_but_not_the_group() -> None:
    cipher = TermCipher(b"k" * 32)
    key = cipher.lookup_key("client", "Ζέφυρος Ναυτιλιακή")
    assert key == cipher.lookup_key("client", "ζεφυροσ   ναυτιλιακη")
    assert key != cipher.lookup_key("project", "Ζέφυρος Ναυτιλιακή")
    assert key != TermCipher(b"x" * 32).lookup_key("client", "Ζέφυρος Ναυτιλιακή")


def test_rows_are_validated_one_by_one() -> None:
    valid, errors = validate_rows(
        [
            {"term": "  Boreas   Energy ", "aliases": "Boreas; BE Ltd", "data_type": "client"},
            {"term": "!!"},
            {"term": "Notos", "aliases": [7]},
            {"term": "Notos", "data_type": "9 lives"},
            {"term": 42},
        ]
    )
    assert [(row.term, row.aliases, row.data_type, row.group) for row in valid] == [
        ("Boreas Energy", ("Boreas", "BE Ltd"), "CLIENT", "client")
    ]
    assert [error.row for error in errors] == [2, 3, 4, 5]
    assert errors[0].message == "term must contain a letter or a digit"


def test_term_files_in_greek_windows_encoding_are_read() -> None:
    rows = parse_term_file("pelates.csv", "Term;Aliases\nΖέφυρος;ZML|Zephyros\n".encode("cp1253"))
    assert rows == [{"term": "Ζέφυρος", "aliases": "ZML|Zephyros"}]
    with pytest.raises(InvalidInputError, match="list"):
        parse_term_file("terms.json", b'{"term": "Notos"}')


def test_document_category_is_not_a_value_type() -> None:
    assert document_category("source code") == "SOURCE_CODE"
    assert document_category("Board minutes") == "BOARD_MINUTES"
    with pytest.raises(InvalidInputError):
        document_category("EMAIL")


def test_text_is_extracted_from_each_supported_format() -> None:
    assert extract_text("a.txt", "Σύμβαση έργου".encode()) == "Σύμβαση έργου"
    assert extract_text("a.md", "Σύμβαση".encode("cp1253")) == "Σύμβαση"
    assert "tariff model called Meltemi" in " ".join(
        extract_text("a.docx", docx_bytes(CONTRACT)).split()
    )
    assert "Annual budget" in extract_text("a.pdf", pdf_bytes(["Annual budget review"]))
    with pytest.raises(UnsupportedFileError):
        extract_text("a.bin", b"\x00\x01\x02")


def test_long_documents_are_masked_in_blocks_that_lose_nothing() -> None:
    text = ("line of text\n" * 900) + ("x" * 20_000) + "\nend"
    blocks = _blocks(text)
    assert "".join(blocks) == text and max(len(block) for block in blocks) <= 8000


def test_crm_clients_and_their_contacts_become_client_terms() -> None:
    rows = terms_from_clients(
        [
            {
                "legal_name": "Zephyros Maritime Ltd",
                "trade_name": "Zephyros Maritime",
                "aliases": ["ZML", "Zephyros Maritime"],
                "contacts": [{"name": "Δανάη Ραφαηλίδου"}, {"name": "Orestis Vamvakas"}],
            },
            {"legal_name": "Ιάσων Δελής", "kind": "individual"},
        ]
    )
    assert rows[0] == {
        "term": "Zephyros Maritime Ltd",
        "aliases": ["Zephyros Maritime", "ZML"],
        "data_type": DataType.CLIENT,
        "group": "crm-clients",
    }
    assert [(row["term"], row["data_type"]) for row in rows[1:]] == [
        ("Δανάη Ραφαηλίδου", DataType.CLIENT),
        ("Orestis Vamvakas", DataType.CLIENT),
        ("Ιάσων Δελής", DataType.CLIENT),
    ]


def test_preview_gives_one_entity_one_placeholder() -> None:
    text = "Maria, Μαρίας, Nikos, key abc"

    def finding(data_type: str, start: int, end: int, maskable: bool = True) -> Finding:
        return Finding(
            data_type=data_type,
            start=start,
            end=end,
            text=text[start:end],
            tier=Tier.T1,
            score=0.9,
            recogniser="test",
            maskable=maskable,
        )

    masked, placeholders = mask_preview(
        text,
        [
            finding(DataType.PERSON, 0, 5),
            finding(DataType.PERSON, 7, 13),
            finding(DataType.PERSON, 15, 20),
            finding(DataType.CONFIDENTIAL_MARKER, 22, 25, maskable=False),
            finding(DataType.SECRET, 26, 29),
        ],
    )
    assert masked == "<PERSON_1>, <PERSON_1>, <PERSON_2>, key <SECRET_REDACTED>"
    assert placeholders == ["<PERSON_1>", "<PERSON_1>", "<PERSON_2>", None, "<SECRET_REDACTED>"]


def test_a_word_file_that_unpacks_to_too_much_is_refused_before_it_is_parsed() -> None:
    """A zip bomb: sixty megabytes of one byte compress to a few kilobytes."""
    bomb = docx_bomb(MAX_EXPANDED_BYTES + 10 * 1024 * 1024)
    assert len(bomb) < 200_000
    started = time.perf_counter()
    with pytest.raises(TooLargeError, match="50 MB") as refusal:
        extract_text("bomb.docx", bomb)
    assert refusal.value.status == 413 and time.perf_counter() - started < 0.5


def test_a_pdf_with_too_many_pages_is_refused() -> None:
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(width=72, height=72)
    packed = io.BytesIO()
    writer.write(packed)
    with pytest.raises(TooLargeError, match="pages"):
        extract_text("long.pdf", packed.getvalue())


def test_a_pdf_stream_that_inflates_past_the_limit_is_refused() -> None:
    """pypdf stops the inflation; the refusal is the same as for any oversized file."""
    content = zlib.compress(b"BT (x) Tj ET\n" + b" " * 80_000_000)
    stream = (
        b"<< /Length "
        + str(len(content)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + content
        + b"\nendstream"
    )
    with pytest.raises(TooLargeError):
        extract_text("bomb.pdf", pdf_document(stream))
