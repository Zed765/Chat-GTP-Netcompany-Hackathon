from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gateway.app.core.types import RehydrationReport
from gateway.app.vault.rehydration import StreamRehydrator

VALUES = {
    "<PERSON_1>": "Μαρία Παπαδοπούλου",
    "<PERSON_12>": "Nikos Georgiou",
    "<AFM_1>": "123456789",
    "<ID_CARD_2>": "ΑΒ 123456",
}
UNKNOWN = ("<PERSON_7>", "<IBAN_1>")


def manglings(placeholder: str) -> list[str]:
    inner = placeholder[1:-1]
    return [
        placeholder,
        placeholder.lower(),
        placeholder.title(),
        f"< {inner} >",
        f"<{inner.replace('_', ' ')}>",
        f"\\<{inner}\\>",
        placeholder.replace("_", "\\_"),
        f"&lt;{inner}&gt;",
        inner,
        inner.lower(),
        placeholder[:-1],
        placeholder[1:],
    ]


def restore(chunks: Sequence[str], sent: Sequence[str] = ()) -> tuple[list[str], RehydrationReport]:
    rehydrator = StreamRehydrator(VALUES, sent)
    released = [rehydrator.feed(chunk) for chunk in chunks]
    released.append(rehydrator.flush())
    return released, rehydrator.report()


def restored(text: str) -> str:
    return "".join(restore([text])[0])


@pytest.mark.parametrize("placeholder", VALUES)
def test_every_mangling_is_restored(placeholder: str) -> None:
    for mangled in manglings(placeholder):
        text = f"Dear {mangled}, your file is ready."
        assert restored(text) == f"Dear {VALUES[placeholder]}, your file is ready.", mangled


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<PERSON_1><AFM_1>", "Μαρία Παπαδοπούλου123456789"),
        ("<PERSON_12> is not <PERSON_1>2", "Nikos Georgiou is not Μαρία Παπαδοπούλου2"),
        ("PERSON_12 is not PERSON_1.", "Nikos Georgiou is not Μαρία Παπαδοπούλου."),
        ("**<PERSON_1>** and `<AFM_1>`", "**Μαρία Παπαδοπούλου** and `123456789`"),
        ("[PERSON_1](mailto:x)", "[Μαρία Παπαδοπούλου](mailto:x)"),
        (r"C:\Users\<PERSON_1>\notes", r"C:\Users\Μαρία Παπαδοπούλου\notes"),
        ("<b>PERSON_1</b>", "<b>Μαρία Παπαδοπούλου</b>"),
        ("η κα <PERSON_1>.", "η κα Μαρία Παπαδοπούλου."),
    ],
)
def test_placeholders_are_restored_in_context(text: str, expected: str) -> None:
    assert restored(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "the PERSON_1_ID column and MY_PERSON_1",
        "xPERSON_1 and person1 and PERSON 1",
        "<h1>Title</h1> in UTF_8, SHA_256",
        "a < b and c > d",
        "<SECRET_REDACTED> stays",
    ],
)
def test_text_that_only_resembles_a_placeholder_is_left_alone(text: str) -> None:
    released, report = restore([text])
    assert "".join(released) == text
    assert report == RehydrationReport(sent=0, returned=0)


def test_unknown_placeholders_are_left_untouched_and_reported() -> None:
    text = "<PERSON_1> wrote to <PERSON_7>, < iban_1 > and <PERSON_7> again."
    released, report = restore([text], sent=["<PERSON_1>", "<AFM_1>"])
    assert "".join(released) == text.replace("<PERSON_1>", VALUES["<PERSON_1>"])
    assert report == RehydrationReport(sent=2, returned=1, unresolved=("<PERSON_7>", "<IBAN_1>"))


def test_the_report_counts_distinct_placeholders_and_never_the_secret_mark() -> None:
    sent = ["<PERSON_1>", "<AFM_1>", "<SECRET_REDACTED>", "<PERSON_1>"]
    _, report = restore(["<PERSON_1>, <person_1> and PERSON_1"], sent=sent)
    assert report == RehydrationReport(sent=2, returned=1)


def test_a_restored_value_is_not_scanned_again() -> None:
    rehydrator = StreamRehydrator({"<ORG_1>": "<PERSON_1> Ltd", "<PERSON_1>": "Maria"}, ())
    assert rehydrator.feed("<ORG_1>") + rehydrator.flush() == "<PERSON_1> Ltd"


SPLIT_TEXTS = [
    "Dear <PERSON_1>, your AFM <AFM_1> is on file.",
    "Η <PERSON_1> και ο <PERSON_12> (ΑΔΤ <ID_CARD_2>).",
    r"\<PERSON_1\> &lt;AFM_1&gt; < person_12 > PERSON_1> <ID CARD 2> <PERSON_7>",
    "PERSON_12 PERSON_1 person_1&gt; x<PERSON_1>y <<AFM_1>>",
]


@pytest.mark.parametrize("text", SPLIT_TEXTS)
def test_a_split_at_any_boundary_gives_the_same_text_and_report(text: str) -> None:
    whole, report = restore([text])
    for cut in range(len(text) + 1):
        released, split_report = restore([text[:cut], text[cut:]])
        assert "".join(released) == "".join(whole), cut
        assert split_report == report, cut


@pytest.mark.parametrize("text", SPLIT_TEXTS)
def test_one_character_at_a_time_gives_the_same_text(text: str) -> None:
    assert "".join(restore(list(text))[0]) == restored(text)


def test_no_part_of_a_placeholder_is_released_before_it_resolves() -> None:
    released, _ = restore(["Dear <PE", "RSON", "_1", ">, hello <AFM", "_9> bye"])
    assert released == ["Dear ", "", "", "Μαρία Παπαδοπούλου, hello ", "<AFM_9> bye", ""]


def test_ordinary_text_is_not_held_back() -> None:
    chunks = ["The quick brown fox, ", "α < β; ", "jumps over ", "the lazy dog"]
    assert restore(chunks)[0] == [*chunks, ""]


def test_flush_releases_an_unfinished_tail_as_it_is() -> None:
    released, _ = restore(["Dear <PERS"])
    assert released == ["Dear ", "<PERS"]


TOKENS = [form for placeholder in (*VALUES, *UNKNOWN) for form in manglings(placeholder)]
PIECES = st.one_of(
    st.sampled_from(TOKENS),
    st.text(alphabet="PERSONafm_12 <>&lt;g\\\n,αβ", max_size=8),
)


@settings(max_examples=500, deadline=None)
@given(pieces=st.lists(PIECES, max_size=12), data=st.data())
def test_the_output_does_not_depend_on_where_the_chunks_are_cut(
    pieces: list[str], data: st.DataObject
) -> None:
    text = "".join(pieces)
    cuts = sorted(data.draw(st.lists(st.integers(0, len(text)), max_size=10)))
    chunks = [text[start:end] for start, end in zip([0, *cuts], [*cuts, len(text)], strict=True)]

    whole, report = restore([text])
    released, chunked_report = restore(chunks)

    assert "".join(released) == "".join(whole)
    assert chunked_report == report
