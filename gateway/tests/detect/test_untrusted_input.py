"""Detection reads text that anyone can send, so no input may make it slow.

Each input below is built to make a careless pattern backtrack: one of them once held the
gateway for twelve seconds at 30 KB. The whole engine runs, language models included.
"""

import base64
import gc
import time
from itertools import pairwise

import pytest

from gateway.app.core.types import DataType, Tier
from gateway.app.detect.fingerprint import chunks, reduce_placeholders
from gateway.app.detect.local import MAX_DECODED_RUNS, MAX_MODEL_CHARS, LocalEngine
from gateway.app.detect.spans import Span, resolve_overlaps

LARGE = 100_000
SMALL = 10_000
# Generous on purpose: the worst input takes under a second here, and the test must not
# fail on a slower machine. A quadratic pattern would need minutes at this size.
BOUND_S = 2.5
# Ten times the text should take about ten times as long. Twenty-five leaves room for
# timer noise on the small input; a quadratic pattern gives a hundred.
MAX_GROWTH = 25

ADVERSARIAL = {
    "percent escapes that are not escapes": "%a",
    "equals signs": "=",
    "a run of hex digits": "0123456789abcdef",
    "a run of base64 letters": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    "digits with spaces": "1 2 3 4 5 6 7 8 9 0 ",
    "digits with dashes": "12-34-56-78-90-",
    "one endless word": "a",
    "capitals joined by hyphens": "A-",
    "capitalised words": "Abcde ",
    "address characters without an at-sign": "a.b%c+d-",
    "at-signs": "a@",
    "thousands of emails": "a@b.co ",
    "credential names": "token.",
    "thousands of markers": "Confidential. ",
    "valid percent escapes": "%41%42%4",
    "half an IBAN": "GR16 0110 ",
    "phone numbers": "+30 694 412 3456 ",
    "placeholders that never close": "<A_",
    "thousands of encoded runs": base64.b64encode(b"hello world!").decode() + " ",
    "Greek prose": "Καλημέρα σας, ",
}


def _text(unit: str, size: int) -> str:
    return (unit * (size // len(unit) + 1))[:size]


def _seconds(engine: LocalEngine, text: str) -> float:
    """The best of three runs, with the garbage collector paused.

    A full collection walks the loaded language models and takes 0.1 to 0.2 s whatever
    the input, so it would look like growth when it lands in the larger run. The gateway
    freezes the models out of the collector at startup.
    """
    best = float("inf")
    gc.collect()
    gc.disable()
    try:
        for _ in range(3):
            started = time.perf_counter()
            engine.detect(text)
            best = min(best, time.perf_counter() - started)
    finally:
        gc.enable()
    return best


@pytest.mark.parametrize("unit", ADVERSARIAL.values(), ids=ADVERSARIAL.keys())
def test_adversarial_text_is_handled_in_linear_time(engine: LocalEngine, unit: str) -> None:
    large = _seconds(engine, _text(unit, LARGE))
    assert large < BOUND_S, f"{LARGE:,} characters took {large:.2f} s"
    small = _seconds(engine, _text(unit, SMALL))
    assert large < MAX_GROWTH * max(small, 0.004), (
        f"{SMALL:,} characters took {small:.3f} s and {LARGE:,} took {large:.3f} s"
    )


def test_long_text_is_still_searched_to_its_end(engine: LocalEngine) -> None:
    """The language models read only the start of a long text; everything else reads it all."""
    filler = _text("Τίποτα το ιδιαίτερο εδώ, μόνο λόγια. ", 3 * MAX_MODEL_CHARS)
    text = f"{filler} ΑΦΜ 094014201, Helios Shipping S.A., ο Γιώργος Νικολάου."
    result = engine.detect(text)
    assert [(finding.data_type, finding.text) for finding in result.findings] == [
        (DataType.AFM, "094014201"),
        (DataType.CLIENT, "Helios Shipping S.A."),
        (DataType.PERSON, "Γιώργος Νικολάου"),
    ]
    assert any("language models" in note for note in result.notes)
    assert engine.detect("ΑΦΜ 094014201").notes == ()


def test_only_so_many_encoded_runs_are_decoded(rules_only: LocalEngine) -> None:
    hidden = base64.b64encode(b"AFM 094014201").decode()
    harmless = base64.b64encode(b"hello world!").decode()
    result = rules_only.detect(f"{hidden} " + f"{harmless} " * (MAX_DECODED_RUNS + 5))
    assert [(finding.data_type, finding.encoded) for finding in result.findings] == [
        (DataType.AFM, True)
    ]
    assert f"Only the first {MAX_DECODED_RUNS} encoded runs were decoded" in result.notes


def test_overlap_resolution_scales_to_many_spans() -> None:
    spans = [
        Span(DataType.EMAIL, start, start + 6, Tier.T0, 0.9, "email")
        for start in range(0, 300_000, 3)
    ]
    started = time.perf_counter()
    kept = resolve_overlaps(spans)
    assert time.perf_counter() - started < 1.0
    assert len(kept) == 50_000
    assert all(left.end <= right.start for left, right in pairwise(kept))


@pytest.mark.parametrize("unit", ["<A_", "<", "<AAAA", "<A_1", "_"])
def test_masked_text_is_prepared_for_fingerprinting_in_linear_time(unit: str) -> None:
    text = _text(unit, LARGE)
    started = time.perf_counter()
    pieces = chunks(reduce_placeholders(text))
    assert time.perf_counter() - started < 0.5 and len(pieces) == 1
