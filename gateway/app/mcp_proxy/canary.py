"""The canary check on outgoing tool calls.

Each agent session gets a random marker that sits in the assistant's system prompt and
nowhere else. If it turns up in the arguments of a tool call, the prompt is on its way out.
"""

import base64
import binascii
import re
from collections.abc import Iterator
from typing import Any

_NOT_ALPHANUMERIC = re.compile(r"[\W_]+")
_WHITESPACE = re.compile(r"\s+")
# A run long enough to hold part of an encoded canary, in the standard or URL-safe alphabet.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{16,}")
_ALIGNMENTS = range(4)


def _squash(text: str) -> str:
    """Letters and digits only, in one case: "ASPIDA canary-0F3A" reads like the original."""
    return _NOT_ALPHANUMERIC.sub("", text).casefold()


def _strings(value: Any) -> Iterator[str]:
    """Every string value in a JSON value, in order. Argument names are not included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _base64_decoded(text: str) -> Iterator[str]:
    """What the base64 runs of a text decode to.

    A run that follows other letters directly starts at an unknown offset, so each of the
    four alignments is tried. Line breaks inside a run are removed first.
    """
    for run in _BASE64_RUN.findall(_WHITESPACE.sub("", text)):
        standard = run.replace("-", "+").replace("_", "/")
        for skip in _ALIGNMENTS:
            whole = len(standard) - skip - (len(standard) - skip) % 4
            try:
                decoded = base64.b64decode(standard[skip : skip + whole])
            except binascii.Error:
                continue
            yield decoded.decode("utf-8", "ignore")


def leaks_canary(arguments: dict[str, Any], canary: str) -> bool:
    """True if the canary is found in the string arguments of a tool call.

    This is a tripwire, not a guarantee. It finds the canary written out, with its case or
    separators changed, reversed, or encoded as hex or base64, in one argument or split over
    several in order. A model that paraphrases, translates or encrypts its instructions gets
    past it, which is why the taint rule and the vault do not depend on it.
    """
    needle = _squash(canary)
    as_hex = canary.encode().hex()
    parts = list(_strings(arguments))
    for text in [*parts, "".join(parts)]:
        squashed = _squash(text)
        if needle in squashed or needle[::-1] in squashed or as_hex in squashed:
            return True
        if any(needle in _squash(decoded) for decoded in _base64_decoded(text)):
            return True
    return False
