"""The protected-terms matcher: company terms, confidentiality markers and the name gazetteer.

Terms are compared word by word through `term_key`, which ignores case and accents, drops
Greek case endings and maps Greek and Greeklish spellings to one form. One pass over the
text therefore finds "Ήλιος Ναυτιλιακή", "Ήλιου Ναυτιλιακής" and "Ilios Naftiliaki".
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from gateway.app.core.types import DataType, RowSource, Store, StoreRef, Tier
from gateway.app.detect.greek_names import NameKind, name_keys
from gateway.app.detect.spans import Span
from gateway.app.detect.tokens import Token, adjacent, name_key, term_key, tokenise

MARKER_GROUP = "confidentiality-markers"
TERM_SCORE = 0.95
MARKER_SCORE = 0.9
# A short all-capitals term is an acronym: it must appear exactly as written.
MAX_ACRONYM_LETTERS = 5
MIN_WORD_LETTERS = 2


# Read over a few characters around the marker only, so the check costs the same anywhere.
LABEL_WINDOW = 9
_LABEL_OPENS = re.compile(r"(?:\A|[\n.!?:;])[ \t\"'«“(\[*#>\-–—]{0,8}\Z")
_LABEL_CLOSES = re.compile(r"[ \t]{0,8}(?:\Z|[\n.:!;,\])»”\"'*\-–—])")


@dataclass(frozen=True, slots=True)
class TermRule:
    row_id: str
    term: str
    aliases: tuple[str, ...]
    data_type: str
    source: RowSource
    group: str

    @property
    def gazetteer_kind(self) -> NameKind | None:
        if self.source is RowSource.DEFAULT and self.group in NameKind:
            return NameKind(self.group)
        return None


@dataclass(frozen=True, slots=True)
class _Entry:
    keys: tuple[str, ...]
    rule: TermRule
    exact: str | None
    proper_noun: bool
    ends_with_dot: bool
    marker: bool


@dataclass(frozen=True, slots=True)
class Gazetteer:
    given: frozenset[str]
    surnames: frozenset[str]

    def is_given(self, token: Token) -> bool:
        return token.capitalised and name_key(token.text) in self.given

    def is_surname(self, token: Token) -> bool:
        return token.capitalised and name_key(token.text) in self.surnames

    def knows(self, token: Token) -> bool:
        return self.is_given(token) or self.is_surname(token)


def _is_label(text: str, start: int, end: int) -> bool:
    """A confidentiality marker marks a text when it stands as a label: in capitals, or on
    its own at the start of a line or sentence. "Offers confidential counselling" is prose."""
    if text[start:end].isupper():
        return True
    opens = _LABEL_OPENS.search(text, max(0, start - LABEL_WINDOW), start)
    return opens is not None and _LABEL_CLOSES.match(text, end) is not None


def _entry(form: str, rule: TermRule) -> _Entry | None:
    words = [token.text for token in tokenise(form)]
    if not words or all(len(word) < MIN_WORD_LETTERS for word in words):
        return None
    marker = rule.data_type == DataType.CONFIDENTIAL_MARKER
    single = len(words) == 1
    acronym = single and words[0].isupper() and len(words[0]) <= MAX_ACRONYM_LETTERS
    return _Entry(
        keys=tuple(term_key(word) for word in words),
        rule=rule,
        exact=words[0] if acronym else None,
        proper_noun=single and not marker,
        ends_with_dot=form.rstrip().endswith("."),
        marker=marker,
    )


class TermMatcher:
    def __init__(self, rules: Iterable[TermRule]) -> None:
        given: set[str] = set()
        surnames: set[str] = set()
        by_first_key: defaultdict[str, list[_Entry]] = defaultdict(list)
        for rule in rules:
            kind = rule.gazetteer_kind
            if kind is NameKind.SURNAME:
                surnames |= name_keys(rule.term, kind)
            elif kind is not None:
                given |= name_keys(rule.term, kind)
            else:
                for form in (rule.term, *rule.aliases):
                    entry = _entry(form, rule)
                    if entry is not None:
                        by_first_key[entry.keys[0]].append(entry)
        # Company rows first, then the longest term, so the best match is found first.
        for entries in by_first_key.values():
            entries.sort(
                key=lambda entry: (entry.rule.source is RowSource.DEFAULT, -len(entry.keys))
            )
        self._by_first_key = dict(by_first_key)
        self.gazetteer = Gazetteer(frozenset(given), frozenset(surnames))

    def find(self, text: str, tokens: Sequence[Token]) -> list[Span]:
        keys = [term_key(token.text) for token in tokens]
        spans: list[Span] = []
        for index, key in enumerate(keys):
            for entry in self._by_first_key.get(key, ()):
                if self._matches(entry, text, tokens, keys, index):
                    end = tokens[index + len(entry.keys) - 1].end
                    # "S.A." keeps its last dot, which the word tokens leave out.
                    if entry.ends_with_dot and text.startswith(".", end):
                        end += 1
                    spans.append(self._span(entry, tokens[index].start, end))
        return spans

    @staticmethod
    def _matches(
        entry: _Entry, text: str, tokens: Sequence[Token], keys: Sequence[str], index: int
    ) -> bool:
        stop = index + len(entry.keys)
        if tuple(keys[index:stop]) != entry.keys:
            return False
        first = tokens[index]
        if entry.exact is not None and first.text != entry.exact:
            return False
        if entry.proper_noun and not first.capitalised:
            return False
        if not all(adjacent(text, tokens[at], tokens[at + 1]) for at in range(index, stop - 1)):
            return False
        return not entry.marker or _is_label(text, first.start, tokens[stop - 1].end)

    @staticmethod
    def _span(entry: _Entry, start: int, end: int) -> Span:
        rule = entry.rule
        marker = rule.data_type == DataType.CONFIDENTIAL_MARKER
        return Span(
            rule.data_type,
            start,
            end,
            Tier.T1,
            MARKER_SCORE if marker else TERM_SCORE,
            "marker" if marker else "term",
            match=StoreRef(
                store=Store.TERMS, row_id=rule.row_id, source=rule.source, label=rule.group
            ),
            canonical=None if marker else rule.term,
            maskable=not marker,
        )
