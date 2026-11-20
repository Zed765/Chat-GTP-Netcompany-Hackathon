"""Regex-only T0 recognisers, held as data and compiled with RE2 so matching stays linear."""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import re2

from gateway.app.core.types import RowSource, Store, StoreRef, Tier
from gateway.app.detect.spans import Span

PATTERN_SCORE = 0.9
# A pattern may name the part to mask; the rest of the match is context.
VALUE_GROUP = "value"
MAX_PROGRAM_MEMORY = 8 << 20


class PatternError(ValueError):
    """The regex is not valid RE2, or it can match nothing useful."""


@dataclass(frozen=True, slots=True)
class PatternRule:
    row_id: str
    name: str
    regex: str
    data_type: str
    source: RowSource
    group: str


class CompiledPattern(Protocol):
    """The part of an RE2 pattern object this module uses; the binding ships no types."""

    @property
    def groupindex(self) -> Mapping[str, int]: ...

    def search(self, text: str) -> object | None: ...

    def finditer(self, text: str) -> Iterator[re.Match[str]]: ...


def _options() -> Any:
    options = re2.Options()
    options.log_errors = False
    options.max_mem = MAX_PROGRAM_MEMORY
    return options


def compile_pattern(regex: str) -> CompiledPattern:
    try:
        compiled = cast(CompiledPattern, re2.compile(regex, _options()))  # type: ignore[no-untyped-call]
    except re2.error as error:
        detail = error.args[0].decode() if isinstance(error.args[0], bytes) else str(error)
        raise PatternError(f"Not a valid RE2 expression: {detail}") from error
    if compiled.search("") is not None:
        raise PatternError("The expression matches empty text")
    return compiled


class PatternMatcher:
    """All enabled patterns behind one RE2 set, so a text is scanned once to pick candidates."""

    def __init__(self, rules: Sequence[PatternRule]) -> None:
        self._rules = tuple(rules)
        self._compiled = tuple(compile_pattern(rule.regex) for rule in self._rules)
        self._set = re2.Set.SearchSet(_options())  # type: ignore[no-untyped-call]
        for rule in self._rules:
            self._set.Add(rule.regex)
        if self._rules:
            self._set.Compile()

    def find(self, text: str) -> list[Span]:
        if not self._rules:
            return []
        spans: list[Span] = []
        # `Match` answers None, not an empty list, when no pattern matches.
        for index in self._set.Match(text) or ():
            rule, compiled = self._rules[index], self._compiled[index]
            ref = StoreRef(
                store=Store.PATTERNS, row_id=rule.row_id, source=rule.source, label=rule.name
            )
            group = compiled.groupindex.get(VALUE_GROUP, 0)
            for match in compiled.finditer(text):
                start, end = match.span(group)
                if end > start:
                    spans.append(
                        Span(
                            rule.data_type,
                            start,
                            end,
                            Tier.T0,
                            PATTERN_SCORE,
                            f"pattern:{rule.name}",
                            match=ref,
                        )
                    )
        return spans
