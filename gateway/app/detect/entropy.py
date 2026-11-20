"""Secrets with no known format: a value assigned to a credential-like name, or a long
random-looking token. Both rest on Shannon entropy rather than on a provider's pattern."""

import math
import re
from collections import Counter
from collections.abc import Iterator, Sequence

from gateway.app.core.types import DataType, Tier
from gateway.app.detect.spans import Span

ASSIGNED_MIN_ENTROPY = 3.5
ASSIGNED_SCORE = 0.8
PASSWORD_MIN_CHARS = 6
TOKEN_MIN_ENTROPY = 4.4
TOKEN_MIN_DIGITS = 3
TOKEN_SCORE = 0.6

_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?<![^\W_])
    (?P<name>[\w.\-]{0,40}?(?:
        (?P<password>passw(?:or)?d|passwd|pwd|passphrase|κωδικ[οό]ς\w*|συνθηματικ[οό]\w*)
        | secret | token | api[_\-]?key | access[_\-]?key | private[_\-]?key | credentials?
    )[\w.\-]{0,20})
    ["']?\s{0,3}(?::=|=>|[:=])\s{0,3}
    (?:(?P<quote>["'])(?P<quoted>[^"'\n]{6,200})(?P=quote) | (?P<bare>[^\s"'<>,;]{6,200}))
    """
)
_TOKEN = re.compile(r"(?<![\w+/=.\-])[A-Za-z0-9+/_\-]{32,200}={0,2}(?![\w+/=\-])")
# Values that stand for a secret instead of being one: variables, templates, code.
_REFERENCE = re.compile(r"^[$%<{\[(*]|[()\[\]{}]|^(?:null|none|true|false|undefined)$", re.I)


def shannon_entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _looks_like_password(value: str) -> bool:
    return len(value) >= PASSWORD_MIN_CHARS and not value.isalpha()


def _looks_random(value: str) -> bool:
    return any(char.isdigit() for char in value) and shannon_entropy(value) >= ASSIGNED_MIN_ENTROPY


def _assigned(text: str) -> Iterator[Span]:
    for match in _ASSIGNMENT.finditer(text):
        group = "quoted" if match["quoted"] is not None else "bare"
        value = match[group]
        if _REFERENCE.search(value):
            continue
        if _looks_like_password(value) if match["password"] else _looks_random(value):
            yield Span(DataType.SECRET, *match.span(group), Tier.T0, ASSIGNED_SCORE, "entropy")


def _tokens(text: str, readable: Sequence[tuple[int, int]]) -> Iterator[Span]:
    decodes_to_text = bytearray(len(text))
    for start, end in readable:
        decodes_to_text[start:end] = b"\x01" * (end - start)
    for match in _TOKEN.finditer(text):
        value = match.group()
        if decodes_to_text[match.start()]:
            continue
        if text[max(0, match.start() - 7) : match.start()] == "base64,":
            continue
        mixed = any(char.islower() for char in value) and any(char.isupper() for char in value)
        digits = sum(char.isdigit() for char in value)
        if mixed and digits >= TOKEN_MIN_DIGITS and shannon_entropy(value) >= TOKEN_MIN_ENTROPY:
            yield Span(DataType.SECRET, match.start(), match.end(), Tier.T0, TOKEN_SCORE, "entropy")


def find_high_entropy(text: str, readable: Sequence[tuple[int, int]] = ()) -> list[Span]:
    """`readable` lists encoded runs that decode to plain text, which are not secrets."""
    return [*_assigned(text), *_tokens(text, readable)]
