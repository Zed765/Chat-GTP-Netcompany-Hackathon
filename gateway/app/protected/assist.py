"""Adds a pattern from an admin's plain-language description of a format.

The model only proposes. Its expression must compile under RE2, find a value in each of its
own examples, and leave its near misses and ordinary text alone before it is kept; it is
then added the way a pattern typed by hand is.
"""

import logging
from collections.abc import Collection

from openai import OpenAIError
from pydantic import BaseModel, Field

from gateway.app.core.types import DataType, RowSource
from gateway.app.detect.patterns import VALUE_GROUP, CompiledPattern, PatternError, compile_pattern
from gateway.app.llm.client import LLM
from gateway.app.protected.errors import ProtectedDataError
from gateway.app.protected.schemas import AssistResult, AssistTurn, PatternIn
from gateway.app.protected.service import ProtectedData

log = logging.getLogger(__name__)

_MODEL_TIMEOUT_S = 45.0
_PATTERN_ATTEMPTS = 3
_NO_ANSWER = (
    "The model did not return something that can be used. Try again, or word it differently."
)
# A pattern that matches any of these would mask everyday writing.
_ORDINARY_TEXT = (
    "Please send the quarterly report to the team by Monday 14 March, around 10:30, room 204.",
    "Thanks for the update. We looked at 3 options and will decide in 2026, after the meeting.",
    "Παρακαλώ στείλτε την αναφορά στην ομάδα έως τη Δευτέρα 14 Μαρτίου, γύρω στις 10:30.",
)

_PATTERN = """\
You help a company's security admin add a detection pattern to an AI firewall.

A pattern is a regular expression. The firewall runs it on what employees send to AI tools
and replaces what it finds with a placeholder. There are two kinds, and most requests fit
one of them.

1. A value with a shape of its own: a ticket number, an employee ID, an order reference.
   Match the value itself.
2. A value with no shape of its own, which is known by the label in front of it: an
   address, a date of birth, a room, a licence. Match the label, then capture the value in
   a group named `value`. Only that group is masked; the label stays in the text. Use this
   kind whenever the admin says "after the word ..." or the value on its own would look
   like ordinary words and numbers. Do not refuse such a request: write the label pattern.

Rules of the expression (RE2 syntax):
- No lookahead, no lookbehind, no backreferences.
- Start with (?i) when letter case should not matter, which is usual for labels.
- \\b only works next to the letters A to Z and digits. Next to Greek or other letters it
  never matches. Before a label that may be Greek, write (?:^|[^\\pL\\pN]) instead, and let
  the `value` group end where a character class or the separator after it ends.
- For a Greek label, cover the accented and unaccented spellings and the common endings
  with character classes and alternatives: διε[ύυ]θυνσ(?:η|ης|ή) rather than one spelling.
  Give the English and the Greek word when the admin names both.
- After a label, require a separator: a colon, an equals sign, a dash, or a word such as
  "is" or "είναι", with optional spaces around it. Without one, a sentence that only
  mentions the label ("please update your address soon") would be masked.
- Capture a free-form value with a bounded negated class, not with "anything": up to the
  end of the line, a semicolon or about 100 characters, for example
  (?P<value>[^\\n;]{{5,100}}). Use plain classes such as [^\\n;] or [A-Za-z0-9] for long
  runs; a long repeat of \\pL is too costly.
- A value with its own shape: spell fixed prefixes out and make digit counts exact, so
  that ordinary words, dates, times and numbers do not match.
- It must not match empty text. Give the expression alone, with no delimiters around it.

An example of the second kind, for "addresses after the word address or διεύθυνση":
(?i)(?:^|[^\\pL\\pN])(?:address|διε[ύυ]θυνσ(?:η|ης|ή))\\s{{0,3}}(?:is|είναι|ειναι|[:=\\-])\\s{{0,3}}(?P<value>[^\\n;]{{5,100}})

Return:
- regex: the expression.
- name: what the value is, in two to five words, for example "Postal address".
- data_type: an upper-case name for this kind of value, such as TICKET or ADDRESS. Reuse a
  type already in use when one fits: {data_types}. Never use {categories}: those are kinds
  of document.
- examples: three short texts as an employee would write them, each holding one value the
  pattern must find. For the second kind, each text includes the label and separator.
- near_misses: two short texts that look similar but hold no such value, which the pattern
  must not match: for the second kind, sentences that only mention the label.

The gateway tries the expression on every example and near miss before keeping it. If you
are shown an earlier expression and why it failed, fix that fault and keep what worked.
The request may come with an earlier request and your answer to it: the admin is then
refining that request, so read the two together.

Set understood to false only when there is nothing to anchor a pattern on: neither a shape
nor a label, such as "any number" or "people's names". One specific word or name is a
protected term, not a pattern: say so. Write `explanation` for the admin in one plain
sentence: what the pattern finds, or why none was written and what to say instead.
"""


class _PatternAnswer(BaseModel):
    understood: bool
    name: str
    regex: str
    data_type: str
    examples: list[str] = Field(description="Texts that each hold one value to find")
    near_misses: list[str] = Field(description="Similar texts that must not match")
    explanation: str


def _names(values: Collection[str]) -> str:
    return ", ".join(sorted(values)) or "none"


def _declined(explanation: str) -> AssistResult:
    return AssistResult(added=[], message=explanation.strip() or _NO_ANSWER)


def _found(compiled: CompiledPattern, text: str) -> str | None:
    """What the pattern would mask in a text: its `value` group, or the whole match."""
    group = compiled.groupindex.get(VALUE_GROUP, 0)
    return next(
        (match.group(group) for match in compiled.finditer(text) if match.group(group)), None
    )


def _pattern_problem(answer: _PatternAnswer) -> str | None:
    """Why the proposed expression cannot be kept, in words the model can act on."""
    try:
        compiled = compile_pattern(answer.regex)
    except PatternError as problem:
        return str(problem)
    if not answer.examples:
        return "It comes with no example to try it on"
    missed = next((text for text in answer.examples if _found(compiled, text) is None), None)
    if missed is not None:
        return f"It finds nothing in its own example {missed!r}"
    wrong = next((text for text in answer.near_misses if _found(compiled, text)), None)
    if wrong is not None:
        return f"It matches {wrong!r}, which it should leave alone"
    caught = next((text for text in _ORDINARY_TEXT if _found(compiled, text)), None)
    return f"It also matches ordinary text: {caught!r}" if caught else None


async def assist(
    request: str, previous: AssistTurn | None, *, llm: LLM, protected: ProtectedData
) -> AssistResult:
    """The pattern that was added, by name, and one sentence about it. Nothing is added when
    the model declines, fails, or returns an expression that cannot be kept. `previous` is
    the request before this one and what came of it, when the admin is refining it."""
    try:
        return await _add_pattern(request, previous, llm, protected)
    except (OpenAIError, ValueError) as failure:
        log.warning("assisted pattern failed (%s)", type(failure).__name__)
        return AssistResult(added=[], message=_NO_ANSWER)
    except ProtectedDataError as refusal:
        return AssistResult(added=[], message=str(refusal))


async def _add_pattern(
    request: str, previous: AssistTurn | None, llm: LLM, protected: ProtectedData
) -> AssistResult:
    instructions = _PATTERN.format(
        data_types=_names(protected.data_types() - DataType.CATEGORIES),
        categories=_names(DataType.CATEGORIES),
    )
    asked = request
    if previous is not None:
        asked = (
            f"Earlier request: {previous.request}\nYour answer to it: {previous.message}\n\n"
            f"The admin now says: {request}"
        )
    text, problem = asked, None
    for _ in range(_PATTERN_ATTEMPTS):
        answer = (
            await llm.structured(
                instructions=instructions,
                text=text,
                schema=_PatternAnswer,
                effort="medium",
                timeout_s=_MODEL_TIMEOUT_S,
            )
        ).value
        if not answer.understood:
            return _declined(answer.explanation)
        problem = _pattern_problem(answer)
        if problem is None:
            added = await protected.add_pattern(
                PatternIn(name=answer.name, regex=answer.regex, data_type=answer.data_type),
                RowSource.UPLOADED,
            )
            example = answer.examples[0]
            masked = _found(compile_pattern(answer.regex), example)
            return AssistResult(
                added=[added.name],
                message=f"Added “{added.name}”: in “{example}” it masks “{masked}”.",
            )
        text = f"{asked}\n\nYour last expression, {answer.regex}, cannot be used. {problem}."
    return AssistResult(added=[], message=f"No pattern was added. {problem}.")
