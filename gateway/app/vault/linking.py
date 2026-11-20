"""Deciding which mentions are the same entity, so one entity keeps one placeholder.

The rules, in order:

1. A mention seen before keeps its placeholder for the whole conversation.
2. Identifiers (AFM, IBAN, email and so on) are one entity only when their normalised
   values are equal. A value found in an encoded run is linked by the run itself.
3. Names are compared without case, accents, script, word order or grammatical case, and
   people, organisations and clients share one namespace, because recognisers disagree on
   which of the three a name is.
4. A shorter mention ("Maria", "Ms Papadopoulou") joins a known longer name when exactly
   one known entity contains all its words.
5. When two known entities contain them (two people called Maria), the short mention is
   ambiguous. It gets a placeholder of its own instead of a guess, and keeps it.
6. A longer name never joins an entity first seen under a shorter name in an earlier text:
   a bare "Maria" does not say which Maria. Within one text the longer names are linked
   first, so the order of mentions does not matter.

Linking works on keys alone. No stored value is decrypted to mask a text.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from gateway.app.core.textnorm import latin_key, stem
from gateway.app.core.types import DataType, Finding
from gateway.app.vault.placeholders import make, type_label

type LinkKey = tuple[str, str, str]
"""`(kind, scope, key)`: one entry of a conversation's forward mapping."""

EXACT = "exact"  # a mention's key -> its placeholder
WORD = "word"  # one word of a name -> the placeholders of the entities containing it
COUNT = "count"  # a type label -> how many placeholders of that type exist

NAME_SCOPE = "NAME"
NAME_TYPES = frozenset({DataType.PERSON, DataType.ORG, DataType.CLIENT})
# Written with optional spaces, dashes and dots that are not part of the value.
_SEPARATED_TYPES = frozenset(
    {DataType.PHONE, DataType.AFM, DataType.AMKA, DataType.IBAN, DataType.CARD, DataType.ID_CARD}
)
IDENTIFIER_TYPES = _SEPARATED_TYPES | {DataType.EMAIL}

_NAME_PART = re.compile(r"[^\W\d_]+|\d+")
# The dots of an abbreviation spelled letter by letter, so "Α.Ε." reads as "ΑΕ".
_ABBREVIATION_DOT = re.compile(r"(?<=\b[^\W\d_])\.(?=[^\W\d_]\b)")
# Case endings as `latin_key` spells them, grouped by declension.
_DECLENSIONS = {
    ending: declension
    for declension, endings in {
        "o": ("os", "ous", "ou", "us", "u", "o", "e", "on"),
        "i": ("is", "i"),
        "a": ("as", "a"),
    }.items()
    for ending in endings
}
_NO_WORDS: frozenset[str] = frozenset()


def _word_key(word: str) -> str:
    """textnorm's stem plus the declension of the ending it dropped. "Μαρία" and "Μαρίας"
    agree; "Μάριος", which has the same stem, stays a different name."""
    spelled = latin_key(word)
    root = stem(spelled)
    declension = _DECLENSIONS.get(spelled[len(root) :])
    return f"{root}/{declension}" if declension else root


_TITLES = frozenset(
    _word_key(title)
    for title in (
        *("mr", "mrs", "ms", "miss", "mister", "dr", "prof"),
        *("κ", "κος", "κα", "κύριος", "κυρία", "δρ", "δις"),
    )
)


def _name_words(text: str) -> frozenset[str]:
    """The words a name is known by. Numbers count as words, so "Helios 2" is not "Helios 3"."""
    parts = _NAME_PART.findall(_ABBREVIATION_DOT.sub("", text))
    words = frozenset(part if part.isdecimal() else _word_key(part) for part in parts)
    return words - _TITLES or words


def _name_key(words: frozenset[str]) -> str:
    return " ".join(sorted(words))


def _value_key(data_type: str, value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    separators = r"[\s\-./()]+" if data_type in _SEPARATED_TYPES else r"\s+"
    return re.sub(separators, "", folded)


@dataclass(frozen=True)
class Mention:
    """One finding, reduced to what linking needs."""

    data_type: str
    surface: str
    scope: str
    keys: tuple[str, ...]
    """Exact keys, the canonical name first."""
    words: frozenset[str] = _NO_WORDS
    """Words of the mention as written. Empty when it links by exact value only."""
    entity_words: frozenset[str] = _NO_WORDS
    """Words a new entity made from this mention is known by."""

    def link_keys(self) -> set[LinkKey]:
        """Every entry of the forward mapping that linking this mention reads or writes."""
        return {
            *((EXACT, self.scope, key) for key in self.keys),
            *((WORD, self.scope, word) for word in self.entity_words),
            _counter(self.data_type),
        }


def _counter(data_type: str) -> LinkKey:
    return (COUNT, type_label(data_type), "")


def mention_of(finding: Finding, surface: str) -> Mention:
    data_type = finding.data_type
    if finding.encoded:
        # An encoded run restores to itself, so it never shares a placeholder with the
        # plain value it decodes to.
        return Mention(data_type, surface, f"{data_type}/encoded", (surface,))
    if data_type in IDENTIFIER_TYPES:
        key = _value_key(data_type, finding.canonical or surface)
        return Mention(data_type, surface, data_type, (key,))
    written = _name_words(surface)
    if not written:
        return Mention(data_type, surface, data_type, (_value_key(data_type, surface),))
    canonical = _name_words(finding.canonical) if finding.canonical else written
    return Mention(
        data_type,
        surface,
        NAME_SCOPE if data_type in NAME_TYPES else data_type,
        tuple(dict.fromkeys((_name_key(canonical), _name_key(written)))),
        written,
        canonical | written,
    )


class Linker:
    """One conversation's forward mapping while one text is masked. It starts from the
    entries read from the store and collects what has to be written back."""

    def __init__(self, known: Mapping[LinkKey, str]) -> None:
        self._links = dict(known)
        self.changed: dict[LinkKey, str] = {}
        self.created: dict[str, str] = {}
        """New placeholders with the surface form each one restores to."""

    def placeholder_for(self, mention: Mention) -> str:
        placeholder = (
            self._seen_before(mention)
            or self._only_entity_containing(mention)
            or self._new_entity(mention)
        )
        for key in mention.keys:
            if (EXACT, mention.scope, key) not in self._links:
                self._set((EXACT, mention.scope, key), placeholder)
        return placeholder

    def _seen_before(self, mention: Mention) -> str | None:
        for key in mention.keys:
            if placeholder := self._links.get((EXACT, mention.scope, key)):
                return placeholder
        return None

    def _only_entity_containing(self, mention: Mention) -> str | None:
        if not mention.words:
            return None
        containing = set.intersection(
            *(set(self._holders((WORD, mention.scope, word))) for word in mention.words)
        )
        return containing.pop() if len(containing) == 1 else None

    def _new_entity(self, mention: Mention) -> str:
        counter = _counter(mention.data_type)
        number = int(self._links.get(counter, "0")) + 1
        placeholder = make(mention.data_type, number)
        self._set(counter, str(number))
        for word in mention.entity_words:
            entry = (WORD, mention.scope, word)
            self._set(entry, " ".join([*self._holders(entry), placeholder]))
        self.created[placeholder] = mention.surface
        return placeholder

    def _holders(self, entry: LinkKey) -> list[str]:
        return self._links.get(entry, "").split()

    def _set(self, entry: LinkKey, value: str) -> None:
        self._links[entry] = self.changed[entry] = value


def link_all(linker: Linker, mentions: Sequence[Mention]) -> list[str]:
    """The placeholder of each mention of one text, given in text order. Before a name is
    linked, the longer names of the same text that contain it are, so a "Maria" joins the
    "Maria Papadopoulou" that follows it."""
    sharing: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    for index, mention in enumerate(mentions):
        for word in mention.entity_words:
            sharing[mention.scope, word].add(index)
    placeholders: dict[int, str] = {}

    def link(index: int) -> None:
        mention = mentions[index]
        own = mention.entity_words
        if index in placeholders:
            return
        if own:
            containing = set.intersection(*(sharing[mention.scope, word] for word in own))
            for other in sorted(containing):
                if len(mentions[other].entity_words) > len(own):
                    link(other)
        placeholders[index] = linker.placeholder_for(mention)

    for index in range(len(mentions)):
        link(index)
    return [placeholders[index] for index in range(len(mentions))]
