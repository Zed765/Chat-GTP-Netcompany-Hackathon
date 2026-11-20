"""Puts a decision into words: what was found, what was done, and what to do instead."""

from collections.abc import Sequence

from gateway.app.core.types import (
    Action,
    Channel,
    DataType,
    Explanation,
    FoundItem,
    PolicyContext,
    Store,
    ToolRef,
    ToolStatus,
    Trust,
)
from gateway.app.policy.document import ON_ERROR_RULE, When
from gateway.app.policy.evaluate import Outcome

_SPANS: dict[str, tuple[str, str]] = {
    DataType.PERSON: ("person name", "person names"),
    DataType.ORG: ("organisation name", "organisation names"),
    DataType.LOCATION: ("location", "locations"),
    DataType.ADDRESS: ("address", "addresses"),
    DataType.EMAIL: ("email address", "email addresses"),
    DataType.PHONE: ("phone number", "phone numbers"),
    DataType.AFM: ("tax number (AFM)", "tax numbers (AFM)"),
    DataType.AMKA: ("social security number (AMKA)", "social security numbers (AMKA)"),
    DataType.IBAN: ("IBAN", "IBANs"),
    DataType.CARD: ("payment card number", "payment card numbers"),
    DataType.ID_CARD: ("ID card number", "ID card numbers"),
    DataType.SECRET: ("secret", "secrets"),
    DataType.CLIENT: ("client name", "client names"),
    DataType.CONFIDENTIAL_MARKER: ("confidentiality marking", "confidentiality markings"),
}
# Each category as "text that looks like ..." and, for short, as a noun.
_CATEGORIES: dict[str, tuple[str, str]] = {
    DataType.CONTRACT: ("a contract", "contract text"),
    DataType.FINANCIAL: ("a financial document", "financial text"),
    DataType.HEALTH: ("health information", "health information"),
    DataType.HR: ("an HR document", "HR text"),
    DataType.SOURCE_CODE: ("source code", "source code"),
    DataType.CLIENT_CONFIDENTIAL: ("client-confidential material", "client-confidential text"),
}
_STATUS = {
    ToolStatus.APPROVED: "an approved tool",
    ToolStatus.TOLERATED: "a tolerated tool",
    ToolStatus.UNAPPROVED: "an unapproved tool",
    ToolStatus.UNKNOWN: "a tool nobody has reviewed yet",
}
_TRUST = {
    Trust.TRUSTED: "a trusted",
    Trust.UNTRUSTED: "an untrusted",
}
_DONE = {
    (Channel.PROMPT, Action.ALLOW): "it was sent unchanged",
    (Channel.PROMPT, Action.REDACT): "each value was replaced with a placeholder before "
    "sending and restored in the answer",
    (Channel.PROMPT, Action.WARN): "it will be sent, with placeholders, only if you confirm",
    (Channel.PROMPT, Action.BLOCK): "it was blocked and nothing was sent",
    (Channel.TOOL_CALL, Action.ALLOW): "it went ahead, with real values where it held placeholders",
    (Channel.TOOL_CALL, Action.REDACT): "it went ahead, with every protected value left as a "
    "placeholder",
    (Channel.TOOL_CALL, Action.WARN): "it will run only if you confirm",
    (Channel.TOOL_CALL, Action.BLOCK): "it was blocked",
    (Channel.TOOL_RESULT, Action.ALLOW): "it was passed to the agent unchanged",
    (Channel.TOOL_RESULT, Action.REDACT): "the agent's model received placeholders instead of "
    "the real values",
    (Channel.TOOL_RESULT, Action.WARN): "the agent may use it only if you confirm",
    (Channel.TOOL_RESULT, Action.BLOCK): "it was withheld from the agent",
}
_AGENT_ADVICE = {
    (Channel.TOOL_CALL, Action.REDACT): "Nothing more is needed: the destination received "
    "placeholders only.",
    (Channel.TOOL_CALL, Action.WARN): "Confirm the call if it is what you asked for.",
    (Channel.TOOL_CALL, Action.BLOCK): "Ask the security team if the agent needs this tool.",
    (Channel.TOOL_RESULT, Action.REDACT): "Nothing more is needed: the model works with "
    "placeholders and the real values stay in the vault.",
    (Channel.TOOL_RESULT, Action.WARN): "Confirm if the agent should use this content.",
    (Channel.TOOL_RESULT, Action.BLOCK): "Ask the security team if the agent needs this content.",
}
_TAINTED_CALL_ADVICE = (
    "Check what the agent read. If you still want this action, ask for it again in a new "
    "conversation."
)
_LOCAL_ONLY = " The deeper checks could not finish, so this rests on local detection alone."


def explain(
    ctx: PolicyContext,
    found: Sequence[FoundItem],
    outcome: Outcome,
    tool: ToolRef | None,
    alternatives: Sequence[ToolRef],
) -> Explanation:
    items = _triggers_first(found, outcome.matched_types)
    triggers = [item for item in items if item.data_type in outcome.matched_types]
    return Explanation(
        summary=_summary(ctx, outcome, tool, items, triggers),
        found=tuple(found),
        rule=outcome.rule,
        action=outcome.action,
        advice=_advice(ctx, outcome, triggers, alternatives),
        alternatives=tuple(alternatives),
    )


def _triggers_first(found: Sequence[FoundItem], matched: Sequence[str]) -> list[FoundItem]:
    """One item per data type, with the types that made the rule match in front."""
    merged: dict[str, FoundItem] = {}
    for item in found:
        earlier = merged.get(item.data_type)
        merged[item.data_type] = (
            item
            if earlier is None
            else earlier.model_copy(
                update={
                    "count": earlier.count + item.count,
                    "encoded": earlier.encoded or item.encoded,
                    "match_label": earlier.match_label or item.match_label,
                }
            )
        )
    return sorted(merged.values(), key=lambda item: item.data_type not in matched)


def _summary(
    ctx: PolicyContext,
    outcome: Outcome,
    tool: ToolRef | None,
    items: Sequence[FoundItem],
    triggers: Sequence[FoundItem],
) -> str:
    subject = _subject(ctx, tool)
    done = _DONE[ctx.channel, outcome.action]
    if outcome.rule == ON_ERROR_RULE:
        return f"The checks on {subject[0].lower()}{subject[1:]} could not finish, so {done}."
    contents = join_words([_phrase(item, counted=True) for item in items]) or "nothing sensitive"
    because = ""
    if outcome.action in (Action.WARN, Action.BLOCK) and 0 < len(triggers) < len(items):
        because = f"because of the {_named(triggers)}, "
    sentence = f"{subject}{_circumstances(ctx, outcome.conditions)} contained {contents}; "
    sentence += f"{because}{done}."
    return sentence + _LOCAL_ONLY if outcome.local_tiers_only else sentence


def _subject(ctx: PolicyContext, tool: ToolRef | None) -> str:
    if ctx.channel is Channel.TOOL_CALL:
        return f"The agent's call to {ctx.tool}" if ctx.tool else "The agent's tool call"
    if ctx.channel is Channel.TOOL_RESULT:
        return f"The result of {ctx.tool}" if ctx.tool else "The tool result"
    if tool is None:
        return "The prompt"
    status = f" ({_STATUS[ctx.tool_status]})" if ctx.tool_status else ""
    return f"The prompt to {tool.name}{status}"


def _circumstances(ctx: PolicyContext, conditions: When) -> str:
    """The facts about the request that the rule looked at, besides the data."""
    notes: list[str] = []
    if conditions.side_effects is not None and ctx.side_effects:
        notes.append("able to send or change data")
    if conditions.tainted is not None and ctx.tainted:
        notes.append("made after the agent read untrusted content")
    if conditions.destination is not None and ctx.destination:
        notes.append(f"going to {_TRUST[ctx.destination]} destination")
    if conditions.source is not None and ctx.source:
        notes.append(f"coming from {_TRUST[ctx.source]} source")
    return f", {' and '.join(notes)}," if notes else ""


def _phrase(item: FoundItem, *, counted: bool) -> str:
    """Counted for the list of what was found; short when naming it again."""
    if item.data_type in DataType.CATEGORIES or item.store is Store.FINGERPRINTS:
        plain = _plain(item.data_type)
        kind, short = _CATEGORIES.get(item.data_type, (plain, f"{plain} text"))
        if not counted:
            return short
        if item.match_label:
            return f'text from the protected document "{item.match_label}" ({kind})'
        return f"text that looks like {kind}"
    custom = _plain(item.data_type)
    singular, plural = _SPANS.get(item.data_type, (f"{custom} value", f"{custom} values"))
    noun = singular if item.count == 1 else plural
    if not counted:
        return noun
    return f"{item.count} {noun}{' in encoded text' if item.encoded else ''}"


def _named(items: Sequence[FoundItem]) -> str:
    return join_words([_phrase(item, counted=False) for item in items])


def _plain(data_type: str) -> str:
    return data_type.replace("_", " ").lower()


def join_words(parts: Sequence[str], last: str = "and") -> str:
    if len(parts) < 2:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} {last} {parts[-1]}"


def _advice(
    ctx: PolicyContext,
    outcome: Outcome,
    triggers: Sequence[FoundItem],
    alternatives: Sequence[ToolRef],
) -> str | None:
    action = outcome.action
    if action is Action.ALLOW:
        return None
    if ctx.channel is not Channel.PROMPT:
        if ctx.channel is Channel.TOOL_CALL and action is Action.BLOCK and ctx.tainted:
            return _TAINTED_CALL_ADVICE
        return _AGENT_ADVICE[ctx.channel, action]
    others = join_words([tool.name for tool in alternatives], "or")
    if outcome.rule == ON_ERROR_RULE:
        return "Try again in a moment." + (f" If it keeps failing, use {others}." if others else "")
    if action is Action.REDACT:
        advice = "Nothing more is needed: the AI tool saw placeholders only."
        return advice + (f" To work with the real values, use {others}." if others else "")
    if action is Action.WARN:
        advice = "Confirm to send it with placeholders, or cancel."
        return advice + (f" You can also use {others} instead." if others else "")
    return _block_advice(triggers, others)


def _block_advice(triggers: Sequence[FoundItem], others: str) -> str:
    if any(item.data_type == DataType.SECRET for item in triggers):
        return "Remove the secret and send again. No AI tool needs a real key, token or password."
    removal = f"remove the {_named(triggers)} and send again" if triggers else ""
    if others and removal:
        return f"Use {others} for this, or {removal}."
    if others:
        return f"Use {others} for this."
    if removal:
        return f"{removal[0].upper()}{removal[1:]}."
    return "Ask the security team if you need this allowed."
