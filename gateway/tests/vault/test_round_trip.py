"""The round trip: mask a text, let an echo upstream send the masked text back in chunks,
restore it, and get the input again."""

from fakeredis import FakeAsyncRedis
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gateway.app.core.types import Finding
from gateway.app.vault import VaultService
from gateway.tests.vault.helpers import CONVERSATION, TTL_SECONDS, VAULT_KEY, finding

# Each entity in one surface form; no two of them are forms of one name.
ENTITIES = [
    ("Maria Papadopoulou", "PERSON"),
    ("Νίκου Γεωργίου", "PERSON"),
    ("Helios Shipping A.E.", "ORG"),
    ("Ωκεανός Ναυτιλιακή", "CLIENT"),
    ("123456789", "AFM"),
    ("GR16 0110 1250 0000 0001 2300 695", "IBAN"),
    ("maria@helios.example", "EMAIL"),
    ("+30 210 1234567", "PHONE"),
    ("Aeolus", "PROJECT"),
    ("Πατησίων 12, Αθήνα", "ADDRESS"),
    ("MTIzNDU2Nzg5", "AFM"),
]
FILLER = st.text(alphabet="abc XYZ αβγ ΔΕ 0189 <>&;\\_.,:/-()\n\t'\"@", max_size=20)
PIECES = st.lists(st.one_of(FILLER, st.sampled_from(ENTITIES)), max_size=14)


def assemble(pieces: list[str | tuple[str, str]]) -> tuple[str, list[Finding]]:
    text = ""
    findings: list[Finding] = []
    for piece in pieces:
        if isinstance(piece, str):
            text += piece
            continue
        surface, data_type = piece
        findings.append(finding(data_type, len(text), surface, encoded=surface == "MTIzNDU2Nzg5"))
        text += surface
    return text, findings


@settings(max_examples=300, deadline=None)
@given(pieces=PIECES, data=st.data())
async def test_masking_then_restoring_an_echo_in_any_chunks_gives_the_input(
    pieces: list[str | tuple[str, str]], data: st.DataObject
) -> None:
    text, findings = assemble(pieces)
    vault = VaultService(FakeAsyncRedis(decode_responses=True), VAULT_KEY, TTL_SECONDS)
    masked = await vault.mask(CONVERSATION, text, findings)
    # The property is about text that does not already hold one of its own placeholders.
    assume((await vault.resolve(CONVERSATION, text))[1].returned == 0)
    for masked_away in findings:
        assert masked_away.text not in masked.text

    cuts = sorted(data.draw(st.lists(st.integers(0, len(masked.text)), max_size=12)))
    bounds = zip([0, *cuts], [*cuts, len(masked.text)], strict=True)
    rehydrator = await vault.rehydrator(CONVERSATION, {span.placeholder for span in masked.spans})
    echoed = "".join(rehydrator.feed(masked.text[start:end]) for start, end in bounds)
    echoed += rehydrator.flush()

    assert echoed == text
    report = rehydrator.report()
    assert report.sent == report.returned == len({span.placeholder for span in masked.spans})
    assert report.unresolved == ()
