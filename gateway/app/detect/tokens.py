"""Word tokens with offsets, and the cached keys the term matcher compares them by."""

import re
from dataclasses import dataclass
from functools import lru_cache

from gateway.app.core.textnorm import latin_key, stem

_WORD = re.compile(r"[^\W_]+")
# What may stand between two words of one term: "Attorney-client", "Smith & Co", "Α. Ε."
_JOINER = re.compile(r"[ \t .\-&'’/]{1,3}")
KEY_CACHE_SIZE = 100_000


@dataclass(frozen=True, slots=True)
class Token:
    start: int
    end: int
    text: str

    @property
    def capitalised(self) -> bool:
        return self.text[0].isupper()


def tokenise(text: str) -> list[Token]:
    return [Token(match.start(), match.end(), match.group()) for match in _WORD.finditer(text)]


def adjacent(text: str, left: Token, right: Token) -> bool:
    return _JOINER.fullmatch(text, left.end, right.start) is not None


@lru_cache(maxsize=KEY_CACHE_SIZE)
def name_key(word: str) -> str:
    """Script- and accent-independent key that keeps the case ending."""
    return latin_key(word)


@lru_cache(maxsize=KEY_CACHE_SIZE)
def term_key(word: str) -> str:
    """As `name_key`, with the case ending dropped, so inflected forms of a term agree."""
    return stem(latin_key(word))
