"""Turns a plain-language instruction into a proposed rule, merged into the policy YAML."""

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openai import OpenAIError
from pydantic import BaseModel, Field

from gateway.app.core.textnorm import transliterate
from gateway.app.core.types import Action, Channel, ToolRef, ToolStatus, Trust
from gateway.app.llm.client import LLM
from gateway.app.policy.document import RESERVED_RULE_NAMES, PolicyDocument, Rule, When, check
from gateway.app.policy.edit import with_rule
from gateway.app.policy.evaluate import STRICTNESS
from gateway.app.policy.schemas import DraftResult
from gateway.app.policy.source import load

log = logging.getLogger(__name__)

_MODEL_TIMEOUT_S = 30.0
_FIX_FIRST = "The policy has validation errors. Fix them, then draft the rule again."
_NO_DRAFT = (
    "The model did not return a rule that can be used. Try again, word the instruction "
    "differently, or write the rule in the editor."
)
_INSTRUCTIONS = """\
You turn a security analyst's instruction into one rule for an AI firewall policy.

Rules are checked in order and the first match wins. A rule has conditions and an action.
Leave a list empty, or a value null, when the instruction does not restrict that condition.
- channel: prompt (a person's prompt to an AI tool), tool_call (an agent calling a tool),
  tool_result (content a tool returned to an agent).
- data: data types found in the content. Use only these: {data_types}.
  CUSTOM stands for every type the company defined itself, whatever its name.
- tool_status: the AI tool's status in the inventory: approved, tolerated, unapproved or
  unknown. Only prompts have one. "Unapproved" in everyday speech usually includes unknown.
- tool: tool slugs. Known AI tools: {tools}.
- team: team names. Known teams: {teams}.
- tainted: the agent session has read untrusted content.
- side_effects: the called tool sends or changes data.
- destination, source: trusted or untrusted.
Actions: allow (forward unchanged), redact (replace values with placeholders and restore
them in the answer), warn (the user must confirm), block.

The current rules, in order: {rules}.
Set insert_before to the existing rule the new one must come before, so that it takes
effect without overriding a stricter rule. Use null to place it above the first rule that
is less strict.
Write `explanation` for the analyst in one or two plain sentences: what the rule does and
what to check. If the instruction is unclear, is not about this policy, or needs more than
one rule, set understood to false and say why in `explanation`.
"""


@dataclass(frozen=True)
class Vocabulary:
    """The names an instruction may refer to."""

    data_types: frozenset[str]
    tools: Sequence[ToolRef]
    teams: Sequence[str]


class _ModelDraft(BaseModel):
    understood: bool
    name: str = Field(description="Short kebab-case name, for example block-contracts-to-unknown")
    action: Action
    channel: list[Channel]
    data: list[str]
    tool_status: list[ToolStatus]
    tool: list[str]
    team: list[str]
    tainted: bool | None
    side_effects: bool | None
    destination: Trust | None
    source: Trust | None
    suggest_approved_alternative: bool
    insert_before: str | None
    explanation: str


@dataclass(frozen=True)
class _Proposal:
    rule: Rule | None
    index: int
    explanation: str


async def draft_rule(
    instruction: str, yaml_text: str, *, llm: LLM, vocabulary: Vocabulary
) -> DraftResult:
    document = (await asyncio.to_thread(check, yaml_text, vocabulary.data_types)).document
    if document is None:
        return DraftResult(yaml=yaml_text, rule_name=None, explanation=_FIX_FIRST)
    proposal = await _from_model(llm, instruction, yaml_text, document, vocabulary)
    if proposal.rule is None:
        return DraftResult(yaml=yaml_text, rule_name=None, explanation=proposal.explanation)
    merged = await asyncio.to_thread(_merged, yaml_text, document, proposal.rule, proposal.index)
    return DraftResult(yaml=merged, rule_name=proposal.rule.name, explanation=proposal.explanation)


def _merged(yaml_text: str, document: PolicyDocument, rule: Rule, index: int) -> str:
    return with_rule(yaml_text, load(yaml_text), document, rule, index)


async def _from_model(
    llm: LLM, instruction: str, yaml_text: str, document: PolicyDocument, vocabulary: Vocabulary
) -> _Proposal:
    """The model's proposal. It holds no rule when the model declined or its answer cannot
    be used; the explanation then says which."""
    instructions = _INSTRUCTIONS.format(
        data_types=", ".join(sorted(vocabulary.data_types)),
        tools=", ".join(tool.slug for tool in vocabulary.tools) or "none",
        teams=", ".join(vocabulary.teams) or "none",
        rules=", ".join(f"{rule.name} ({rule.action.value})" for rule in document.rules),
    )
    try:
        answer = await llm.structured(
            instructions=instructions,
            text=f"Instruction: {instruction}\n\nCurrent policy:\n{yaml_text}",
            schema=_ModelDraft,
            effort="medium",
            timeout_s=_MODEL_TIMEOUT_S,
        )
        draft = answer.value
        if not draft.understood:
            return _Proposal(None, 0, draft.explanation)
        rule = _rule(draft.name, _model_conditions(draft), draft.action, document)
    except (OpenAIError, ValueError) as exc:
        log.warning("model drafting failed (%s)", type(exc).__name__)
        return _Proposal(None, 0, _NO_DRAFT)
    if not vocabulary.data_types.issuperset(rule.when.data or ()):
        return _Proposal(None, 0, _NO_DRAFT)
    if draft.suggest_approved_alternative:
        rule = rule.model_copy(update={"suggest": "approved_alternative"})
    names = [existing.name for existing in document.rules]
    if draft.insert_before in names:
        index = min(names.index(draft.insert_before), _first_catch_all(document.rules))
        placement = f"It sits above `{names[index]}`."
    else:
        index = _position(document.rules, rule.action)
        placement = _placement(document.rules, index, rule.action)
    return _Proposal(rule, index, f"{draft.explanation.strip()} {placement}")


def _rule(name: str, conditions: dict[str, Any], action: Action, document: PolicyDocument) -> Rule:
    taken = {rule.name for rule in document.rules} | RESERVED_RULE_NAMES
    base = _slug(name) or "rule"
    unique, suffix = base, 2
    while unique in taken:
        unique, suffix = f"{base}-{suffix}", suffix + 1
    return Rule.model_validate({"name": unique, "when": conditions, "action": action})


def _present(conditions: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in conditions.items() if value not in (None, [])}


def _model_conditions(draft: _ModelDraft) -> dict[str, Any]:
    return _present(draft.model_dump(include=set(When.model_fields)))


def _first_catch_all(rules: Sequence[Rule]) -> int:
    return next(
        (index for index, rule in enumerate(rules) if rule.when.matches_everything), len(rules)
    )


def _position(rules: Sequence[Rule], action: Action) -> int:
    """Above the first rule that is less strict. An allow goes just below the block rules."""
    bar = STRICTNESS[Action.BLOCK if action is Action.ALLOW else action]
    for index, rule in enumerate(rules):
        if rule.when.matches_everything or STRICTNESS[rule.action] < bar:
            return index
    return len(rules)


def _placement(rules: Sequence[Rule], index: int, action: Action) -> str:
    if index == len(rules):
        return "It goes last."
    below = rules[index].name
    if action is Action.ALLOW:
        return f"It sits below the block rules, so they still win, and above `{below}`."
    return f"It sits above `{below}`, the first rule that is less strict, so stricter rules win."


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", transliterate(text)).strip("-")[:100]
