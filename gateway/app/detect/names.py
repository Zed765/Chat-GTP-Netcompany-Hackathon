"""Decides which name candidates are people, using the gazetteer as supporting evidence.

A gazetteer word alone is never a finding, because many names are ordinary words. It
counts when the language model also saw a person there, when a title precedes it, when a
given name stands next to a surname, or when a given name is followed by a capitalised
word that ends the way Greek surnames do.
"""

from collections.abc import Iterator, Sequence

from gateway.app.core.textnorm import fold
from gateway.app.core.types import DataType, Tier
from gateway.app.detect.companies import is_sector, is_unit_word
from gateway.app.detect.spans import Span
from gateway.app.detect.terms import Gazetteer
from gateway.app.detect.tokens import Token, adjacent, name_key

FULL_NAME_SCORE = 0.9
TITLED_NAME_SCORE = 0.85
LIKELY_SURNAME_SCORE = 0.8
NER_NAME_SCORE = 0.85
SUPPORTED_NER_NAME_SCORE = 0.95
SUPPORTED_SINGLE_NAME_SCORE = 0.75
GAZETTEER_RECOGNISER = "gazetteer"

_TITLES = frozenset(
    fold(title)
    for title in (
        "κ", "κος", "κα", "κυρία", "κυρίας", "κύριος", "κύριο", "κύριε", "κυρίου", "δρ", "καθ",
        "Mr", "Mrs", "Ms", "Miss", "Dr", "Prof",
    )
)  # fmt: skip


# How Greek surnames end, in the script-independent key: Venizelos, Papadakis, Samaras,
# Georgiou, Venizelidios. The language model misses such a surname in Latin letters when
# the sentence is short, and no list can hold them all.
_SURNAME_ENDINGS = ("is", "os", "as", "ou", "es")
_MIN_SURNAME_LETTERS = 6


def _likely_surname(token: Token) -> bool:
    key = name_key(token.text)
    return (
        token.capitalised
        and token.text.isalpha()
        and len(key) >= _MIN_SURNAME_LETTERS
        and key.endswith(_SURNAME_ENDINGS)
        and not is_sector(token)
        and not is_unit_word(token)
    )


def _runs(text: str, tokens: Sequence[Token], gazetteer: Gazetteer) -> Iterator[list[Token]]:
    """Maximal runs of adjacent capitalised words that the gazetteer knows."""
    run: list[Token] = []
    for token in tokens:
        if gazetteer.knows(token) and (not run or adjacent(text, run[-1], token)):
            run.append(token)
            continue
        if run:
            yield run
        run = [token] if gazetteer.knows(token) else []
    if run:
        yield run


def _is_full_name(run: Sequence[Token], gazetteer: Gazetteer) -> bool:
    return any(
        gazetteer.is_given(first) and gazetteer.is_surname(second)
        for first in run
        for second in run
        if first is not second
    )


def _gazetteer_names(text: str, tokens: Sequence[Token], gazetteer: Gazetteer) -> Iterator[Span]:
    by_start = {token.start: index for index, token in enumerate(tokens)}
    for run in _runs(text, tokens, gazetteer):
        before = by_start[run[0].start] - 1
        titled = (
            before >= 0
            and fold(tokens[before].text) in _TITLES
            and adjacent(text, tokens[before], run[0])
        )
        after = by_start[run[-1].start] + 1
        surname = (
            tokens[after]
            if after < len(tokens)
            and gazetteer.is_given(run[-1])
            and adjacent(text, run[-1], tokens[after])
            and _likely_surname(tokens[after])
            else None
        )
        end = run[-1].end
        if _is_full_name(run, gazetteer):
            score = FULL_NAME_SCORE
        elif titled:
            score = TITLED_NAME_SCORE
        elif surname is not None:
            score, end = LIKELY_SURNAME_SCORE, surname.end
        else:
            continue
        yield Span(DataType.PERSON, run[0].start, end, Tier.T1, score, GAZETTEER_RECOGNISER)


def _inside(span: Span, tokens: Sequence[Token]) -> list[Token]:
    return [token for token in tokens if span.start <= token.start and token.end <= span.end]


def is_misread_person(span: Span, tokens: Sequence[Token], gazetteer: Gazetteer) -> bool:
    """The language model sometimes calls a person an organisation. Two or three
    capitalised words that start with a known given name are a person."""
    inside = _inside(span, tokens)
    return (
        span.data_type == DataType.ORG
        and len(inside) in (2, 3)
        and all(token.capitalised for token in inside)
        and gazetteer.is_given(inside[0])
        and not any(is_sector(token) for token in inside)
    )


def _supported(span: Span, tokens: Sequence[Token], gazetteer: Gazetteer) -> Span | None:
    """Rescore a person the language model found by what the gazetteer says about it."""
    inside = _inside(span, tokens)
    known = any(gazetteer.knows(token) for token in inside)
    if not known and any(is_unit_word(token) for token in inside):
        return None
    if len(inside) > 1:
        score = SUPPORTED_NER_NAME_SCORE if known else NER_NAME_SCORE
    elif known:
        score = SUPPORTED_SINGLE_NAME_SCORE
    else:
        return None
    return Span(DataType.PERSON, span.start, span.end, Tier.T1, score, span.recogniser)


def is_internal_unit(span: Span, tokens: Sequence[Token]) -> bool:
    """ "Διεύθυνση Ανθρώπινου Δυναμικού" is a department, whatever the language model says."""
    inside = _inside(span, tokens)
    return span.data_type == DataType.ORG and bool(inside) and is_unit_word(inside[0])


def find_people(
    text: str, tokens: Sequence[Token], gazetteer: Gazetteer, candidates: Sequence[Span]
) -> list[Span]:
    """People from the language model's candidates and the gazetteer, merged where they
    overlap so that "Maria" and "Maria Papadopoulou" become one span."""
    evidence = [
        *_gazetteer_names(text, tokens, gazetteer),
        *(
            supported
            for candidate in candidates
            if (supported := _supported(candidate, tokens, gazetteer)) is not None
        ),
    ]
    merged: list[Span] = []
    for span in sorted(evidence, key=lambda span: span.start):
        last = merged[-1] if merged else None
        if last is not None and span.start < last.end:
            best = max(last, span, key=lambda span: span.score)
            merged[-1] = Span(
                DataType.PERSON,
                last.start,
                max(last.end, span.end),
                Tier.T1,
                best.score,
                best.recogniser,
            )
        else:
            merged.append(span)
    return merged
