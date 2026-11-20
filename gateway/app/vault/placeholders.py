"""The placeholder format. Everything that writes, reads or recognises a placeholder goes
through this module, so the format can change in one place.

A placeholder is `<TYPE_N>`: the data type in upper case, then a number that counts the
entities of that type in one conversation. `<SECRET_REDACTED>` is the one-way mark left
where a secret was removed.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from gateway.app.core.types import DataType

# Telling the model that the tokens are safe matters as much as telling it to copy them: a
# model that takes them for sensitive data hedges, refuses or leaves them out of its answer.
PLACEHOLDER_INSTRUCTION = (
    "Tokens in angle brackets such as <PERSON_1> or <IBAN_2> stand in for real values. Treat "
    "each one as the value itself and use it freely: a token is not sensitive information, so "
    "do not avoid it, warn about it or ask for what is behind it. Copy it exactly as written, "
    "brackets included; never translate, alter or split it, never guess the value behind it, "
    "and never make up a token that was not given to you."
)
SECRET_PLACEHOLDER = "<SECRET_REDACTED>"  # noqa: S105

MAX_LABEL_CHARS = 24
# The longest tail a stream holds back. The patterns below are bounded so that no token,
# however mangled, is longer than this.
HOLD_BACK_CHARS = 56

_LETTER = r"[^\W\d_]"
_ALNUM = r"[^\W_]"
_CANONICAL = re.compile(rf"<({_LETTER}{_ALNUM}*(?:_{_ALNUM}+)*)_(\d+)>")

# What a model may do to a placeholder: change its case, add spaces, escape the brackets
# (`\<`, `&lt;`), escape or drop the underscore, or drop one or both brackets.
_OPEN = r"(?:\\?<|&lt;)"
_CLOSE = r"(?:\\?>|&gt;)"
_BRACKETED = (
    rf"{_OPEN}[ \t]{{0,3}}(?P<inner>{_LETTER}[\w\\ \t]{{0,32}}?\d{{1,6}})[ \t]{{0,3}}"
    rf"(?P<close>{_CLOSE})"
)
_BARE = (
    rf"(?:{_OPEN}|(?<![\w\\]))(?P<bare>{_LETTER}[\w\\]{{0,32}}?\\?_\d{{1,6}})(?!\w)"
    rf"(?P<stray>{_CLOSE})?"
)
_TOLERANT = re.compile(rf"{_BRACKETED}|{_BARE}", re.IGNORECASE)
_SECRET = re.compile(re.escape(SECRET_PLACEHOLDER))

# Tails of a stream that could still grow into a placeholder.
_OPEN_TAIL = re.compile(rf"{_OPEN}[\w\\ \t]*(?:&(?:gt?)?)?$", re.IGNORECASE)
_BARE_TAIL = re.compile(rf"(?<![\w\\])(?P<word>{_LETTER}[\w\\]*)(?:&(?:gt?)?)?$", re.IGNORECASE)
_ESCAPE_TAIL = re.compile(r"(?:\\|&(?:[lg]t?)?)$", re.IGNORECASE)


@dataclass(frozen=True)
class PlaceholderSpan:
    """A placeholder found in a text."""

    start: int
    end: int
    placeholder: str
    data_type: str


@dataclass(frozen=True)
class Candidate:
    """Something in model output that may be a placeholder, however it was mangled."""

    start: int
    end: int
    key: str
    well_formed: str | None
    """The exact spelling, when the token has both brackets and reads as `<TYPE_N>`."""


def type_label(data_type: str) -> str:
    """A data type as it appears inside a placeholder. Custom types may hold any characters."""
    label = re.sub(r"[\W_]+", "_", data_type.upper())[:MAX_LABEL_CHARS].strip("_")
    if not label:
        return "VALUE"
    return label if label[0].isalpha() else f"TYPE_{label}"


def make(data_type: str, number: int) -> str:
    return f"<{type_label(data_type)}_{number}>"


def parse(placeholder: str) -> tuple[str, int] | None:
    """The type label and number of an exactly spelled placeholder."""
    match = _CANONICAL.fullmatch(placeholder)
    if match is None or match[1] != match[1].upper():
        return None
    return match[1], int(match[2])


def lookup_key(token: str) -> str:
    """Letters and digits only, so every mangled spelling of a placeholder has one key."""
    return re.sub(r"[\W_]+", "", token).casefold()


def _well_formed(inner: str) -> str | None:
    spelled = "<" + inner.replace("\\", "").upper() + ">"
    return spelled if parse(spelled) else None


def candidates(text: str) -> Iterator[Candidate]:
    """Every token that could be a placeholder, exact or mangled, in order."""
    for match in _TOLERANT.finditer(text):
        start = match.start()
        close = match["close"] or match["stray"] or ""
        # A backslash before "<" belongs to the token only when ">" is escaped too;
        # otherwise it is the user's own, as in `C:\Users\<PERSON_1>`.
        if text[start] == "\\" and not close.startswith("\\"):
            start += 1
        inner = match["inner"]
        if inner is None:
            yield Candidate(start, match.end(), lookup_key(match["bare"]), None)
        else:
            yield Candidate(start, match.end(), lookup_key(inner), _well_formed(inner))


def find_placeholders(text: str) -> list[PlaceholderSpan]:
    """The placeholders in a text with their types, in order.

    Finds bracketed tokens in any case or spacing and reports them in their exact spelling.
    `<SECRET_REDACTED>` is reported with type `SECRET`.
    """
    found = [
        PlaceholderSpan(match.start(), match.end(), SECRET_PLACEHOLDER, DataType.SECRET)
        for match in _SECRET.finditer(text)
    ]
    for candidate in candidates(text):
        if candidate.well_formed and (parsed := parse(candidate.well_formed)):
            found.append(
                PlaceholderSpan(candidate.start, candidate.end, candidate.well_formed, parsed[0])
            )
    return sorted(found, key=lambda span: span.start)


def held_back_from(buffer: str, may_continue: Callable[[str], bool]) -> int:
    """Where the tail that could still become a placeholder starts; `len(buffer)` if none.

    `may_continue` says whether a lookup key begins a placeholder the caller knows, which
    keeps ordinary words flowing: a bare word is held only if it could be a known
    placeholder that lost its brackets.
    """
    window = max(0, len(buffer) - HOLD_BACK_CHARS)
    if opened := _OPEN_TAIL.search(buffer, window):
        return opened.start()
    word = _BARE_TAIL.search(buffer, window)
    if word and may_continue(lookup_key(word["word"])):
        return word.start()
    escape = _ESCAPE_TAIL.search(buffer, window)
    return escape.start() if escape else len(buffer)
