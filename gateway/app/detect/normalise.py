"""Normalisation before detection: strip invisible characters and apply Unicode NFKC,
keeping a map back to the original text so findings can point at what the user typed."""

import re
import unicodedata
from dataclasses import dataclass

# Zero-width and other invisible characters: joiners, soft hyphen, bidi marks, BOM.
_INVISIBLE = re.compile("[­͏؜᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]")


@dataclass(frozen=True)
class NormalisedText:
    """`text` is what the recognisers read. `starts[i]` and `ends[i]` are the bounds, in the
    original text, of the characters that produced `text[i]`; both are None when nothing
    changed."""

    text: str
    starts: tuple[int, ...] | None = None
    ends: tuple[int, ...] | None = None

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if self.starts is None or self.ends is None:
            return start, end
        return self.starts[start], self.ends[end - 1]


def normalise(text: str) -> NormalisedText:
    if text.isascii() or (unicodedata.is_normalized("NFKC", text) and not _INVISIBLE.search(text)):
        return NormalisedText(text)
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(text):
        if _INVISIBLE.match(text[index]):
            index += 1
            continue
        # A base character and its combining marks normalise together.
        stop = index + 1
        while stop < len(text) and unicodedata.combining(text[stop]):
            stop += 1
        for char in unicodedata.normalize("NFKC", text[index:stop]):
            chars.append(char)
            starts.append(index)
            ends.append(stop)
        index = stop
    return NormalisedText("".join(chars), tuple(starts), tuple(ends))
