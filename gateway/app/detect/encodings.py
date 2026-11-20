"""Finds base64, hex and URL-encoded runs that decode to readable text.

Every pattern here reads untrusted text, so each is linear: a run is one character class
repeated, and it can only start where the character before is outside that class.
"""

import base64
import binascii
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import unquote

MIN_BASE64_CHARS = 12
MIN_HEX_CHARS = 16
MIN_DECODED_CHARS = 6
MIN_READABLE_RATIO = 0.7

_BASE64 = re.compile(
    rf"(?<![A-Za-z0-9+/=_\-])[A-Za-z0-9+/_\-]{{{MIN_BASE64_CHARS},}}={{0,2}}(?![A-Za-z0-9+/=_\-])"
)
_HEX = re.compile(rf"(?<![0-9A-Za-z])(?:0x)?((?:[0-9A-Fa-f]{{2}}){{{MIN_HEX_CHARS // 2},}})(?!\w)")
# A URL-encoded run is found from a percent escape outwards: back to the start of the
# stretch of URL characters around it, then forward over the whole stretch.
_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_URL_RUN = re.compile(r"[A-Za-z0-9._~!$&'()*+,;=:@/?%\-]+")
_URL_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~!$&'()*+,;=:@/?%-"
)
_URL_SAFE_TO_STANDARD = str.maketrans("-_", "+/")


@dataclass(frozen=True, slots=True)
class DecodedRun:
    start: int
    end: int
    text: str
    encoding: str


def _readable(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < MIN_DECODED_CHARS:
        return None
    if not all(char.isprintable() or char in "\n\r\t" for char in text):
        return None
    wordlike = sum(char.isalnum() or char.isspace() for char in text)
    return text if wordlike >= MIN_READABLE_RATIO * len(text) else None


def _from_base64(run: str) -> str | None:
    body = run.rstrip("=").translate(_URL_SAFE_TO_STANDARD)
    if len(body) % 4 == 1:
        return None
    try:
        raw = base64.b64decode(body + "=" * (-len(body) % 4), validate=True)
    except binascii.Error:
        return None
    return _readable(raw)


def _from_url(run: str) -> str | None:
    try:
        text = unquote(run, errors="strict")
    except UnicodeDecodeError:
        return None
    return _readable(text.encode())


def decoded_runs(text: str) -> Iterator[DecodedRun]:
    """Every encoded run in `text` whose content reads as text, with the content decoded."""
    in_hex = bytearray(len(text))
    for match in _HEX.finditer(text):
        decoded = _readable(bytes.fromhex(match.group(1)))
        if decoded is not None:
            in_hex[match.start() : match.end()] = b"\x01" * (match.end() - match.start())
            yield DecodedRun(match.start(), match.end(), decoded, "hex")
    for match in _BASE64.finditer(text):
        if in_hex[match.start()]:
            continue
        decoded = _from_base64(match.group())
        if decoded is not None:
            yield DecodedRun(match.start(), match.end(), decoded, "base64")
    scanned = 0
    for escape in _ESCAPE.finditer(text):
        if escape.start() < scanned:
            continue
        start = escape.start()
        # Never back past the previous run, so each character is read once in each direction.
        while start > scanned and text[start - 1] in _URL_CHARS:
            start -= 1
        run = _URL_RUN.match(text, start)
        if run is None:
            continue
        scanned = run.end()
        decoded = _from_url(run.group())
        if decoded is not None:
            yield DecodedRun(run.start(), run.end(), decoded, "URL encoding")
