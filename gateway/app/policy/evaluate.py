"""First-match evaluation of a policy document. Pure and synchronous, so replay can reuse it."""

from collections.abc import Collection
from dataclasses import dataclass

from gateway.app.core.types import Action, Channel, DataType, PolicyContext, ToolRef, ToolStatus
from gateway.app.policy.document import (
    NO_MATCH_RULE,
    ON_ERROR_RULE,
    OnErrorAction,
    PolicyDocument,
    Rule,
    When,
)

STRICTNESS = {Action.ALLOW: 0, Action.REDACT: 1, Action.WARN: 2, Action.BLOCK: 3}
NO_CONDITIONS = When()


@dataclass(frozen=True)
class Outcome:
    action: Action
    rule: str
    matched_types: tuple[str, ...] = ()
    conditions: When = NO_CONDITIONS
    suggest_alternative: bool = False
    local_tiers_only: bool = False


def with_tool_status(ctx: PolicyContext, known: ToolStatus | None = None) -> PolicyContext:
    """A prompt always goes to a tool with a status. When the caller gives none it is the
    inventory's, or `unknown`, so that a missing status can never loosen a decision."""
    if ctx.channel is not Channel.PROMPT or ctx.tool_status is not None:
        return ctx
    return ctx.model_copy(update={"tool_status": known or ToolStatus.UNKNOWN})


def evaluate(policy: PolicyDocument, ctx: PolicyContext) -> Outcome:
    if ctx.detector_error and _on_error(policy, ctx) is OnErrorAction.BLOCK:
        return Outcome(Action.BLOCK, ON_ERROR_RULE, suggest_alternative=True)
    for rule in policy.rules:
        if matches(rule.when, ctx):
            return _outcome(rule, ctx)
    return Outcome(Action.ALLOW, NO_MATCH_RULE, local_tiers_only=ctx.detector_error)


def is_milder_at(policy: PolicyDocument, ctx: PolicyContext, tool: ToolRef, than: Action) -> bool:
    """Whether the same request, sent to `tool` instead, would get a milder action."""
    there = ctx.model_copy(update={"tool": tool.slug, "tool_status": tool.status})
    return STRICTNESS[evaluate(policy, there).action] < STRICTNESS[than]


def matches(when: When, ctx: PolicyContext) -> bool:
    return (
        _one_of(when.channel, ctx.channel)
        and _one_of(when.tool_status, ctx.tool_status)
        and _one_of(when.destination, ctx.destination)
        and _one_of(when.source, ctx.source)
        and _named(when.tool, ctx.tool)
        and _named(when.team, ctx.team)
        and when.tainted in (None, ctx.tainted)
        and when.side_effects in (None, ctx.side_effects)
        and (when.data is None or bool(_found_types(when.data, ctx.data_types)))
    )


def _on_error(policy: PolicyDocument, ctx: PolicyContext) -> OnErrorAction:
    # Agent tool calls and results carry no tool status; they follow the in-house assistant's.
    return policy.on_error[ctx.tool_status or ToolStatus.APPROVED]


def _found_types(wanted: Collection[str], found: frozenset[str]) -> tuple[str, ...]:
    """The found types that a rule's `data` list names, in the rule's order. `CUSTOM` names
    every found type that is not built in, so a rule covers a company's own types before
    anyone has written them into the policy."""
    named: list[str] = []
    for data_type in wanted:
        own = sorted(found - DataType.BUILT_IN) if data_type == DataType.CUSTOM else []
        named += [name for name in (data_type, *own) if name in found and name not in named]
    return tuple(named)


def _outcome(rule: Rule, ctx: PolicyContext) -> Outcome:
    return Outcome(
        action=rule.action,
        rule=rule.name,
        matched_types=_found_types(rule.when.data or (), ctx.data_types),
        conditions=rule.when,
        suggest_alternative=rule.suggest is not None or rule.action is Action.BLOCK,
        local_tiers_only=ctx.detector_error,
    )


def _one_of[T](allowed: Collection[T] | None, actual: T | None) -> bool:
    return allowed is None or actual in allowed


def _named(allowed: Collection[str] | None, actual: str | None) -> bool:
    if allowed is None:
        return True
    return actual is not None and actual.casefold() in {name.casefold() for name in allowed}
