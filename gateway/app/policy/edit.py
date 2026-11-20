"""Changes to policy YAML that keep the analyst's comments and layout.

Each edit works on the text, then checks that the result parses to the intended document.
If it does not (flow style, unusual layout), the document is written out afresh instead.
"""

import re
from typing import Any

import yaml
from pydantic import ValidationError

from gateway.app.core.types import InjectionProtection
from gateway.app.policy.document import PolicyDocument, Rule
from gateway.app.policy.source import Source, YamlSyntaxError, load

_LEVEL = re.compile(
    r"^(?P<key>injection_protection:[ \t]*)[^\s#]+(?P<rest>[ \t]*(?:#.*)?)$", re.MULTILINE
)
_RULES_KEY = re.compile(r"^rules:", re.MULTILINE)
_RULE_ITEM = re.compile(r"^(?P<indent>[ \t]*)- ")
# Written as lists even with one value, as policy files usually have them.
_ALWAYS_LISTS = ("data", "tool_status")


def with_injection_protection(
    text: str, document: PolicyDocument, level: InjectionProtection
) -> str:
    wanted = document.model_copy(update={"injection_protection": level})
    edited, replaced = _LEVEL.subn(rf"\g<key>{level.value}\g<rest>", text, count=1)
    if not replaced:
        edited = _RULES_KEY.sub(f"injection_protection: {level.value}\n\nrules:", text, count=1)
    return edited if _parses_to(edited, wanted) else render(wanted)


def with_rule(text: str, source: Source, document: PolicyDocument, rule: Rule, index: int) -> str:
    """Insert `rule` so that it becomes `rules[index]`."""
    wanted = document.model_copy(
        update={"rules": (*document.rules[:index], rule, *document.rules[index:])}
    )
    edited = _insert_rule_text(text, source, len(document.rules), rule, index)
    return edited if edited and _parses_to(edited, wanted) else render(wanted)


def render(document: PolicyDocument) -> str:
    plain = {
        "version": document.version,
        "on_error": {status.value: action.value for status, action in document.on_error.items()},
        "injection_protection": document.injection_protection.value,
        "rules": [plain_rule(rule) for rule in document.rules],
    }
    return _dump(plain)


def plain_rule(rule: Rule) -> dict[str, Any]:
    when = {
        key: value[0] if _is_single(key, value) else value
        for key, value in rule.when.model_dump(mode="json", exclude_none=True).items()
    }
    plain: dict[str, Any] = {"name": rule.name}
    if when:
        plain["when"] = when
    plain["action"] = rule.action.value
    if rule.suggest:
        plain["suggest"] = rule.suggest
    return plain


def _is_single(key: str, value: Any) -> bool:
    return isinstance(value, list) and len(value) == 1 and key not in _ALWAYS_LISTS


def _dump(value: Any) -> str:
    return yaml.safe_dump(
        value, default_flow_style=None, sort_keys=False, allow_unicode=True, width=100
    )


def _parses_to(text: str, wanted: PolicyDocument) -> bool:
    try:
        return PolicyDocument.model_validate(load(text).data) == wanted
    except (YamlSyntaxError, ValidationError):
        return False


def _insert_rule_text(text: str, source: Source, rules: int, rule: Rule, index: int) -> str | None:
    lines = text.splitlines(keepends=True)
    first = source.lines[("rules", 0)] - 1
    last = source.lines[("rules", rules - 1)] - 1
    item = _RULE_ITEM.match(lines[first])
    if item is None:
        return None
    block = [f"{item['indent']}{line}\n" for line in _dump([plain_rule(rule)]).splitlines()]
    spaced = any(not line.strip() for line in lines[first:last])
    if index == rules:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return "".join(lines + (["\n"] if spaced else []) + block)
    at = source.lines[("rules", index)] - 1
    # Comments directly above a rule belong to it, so the new rule goes above them.
    while at > 0 and lines[at - 1].lstrip().startswith("#"):
        at -= 1
    return "".join(lines[:at] + block + (["\n"] if spaced else []) + lines[at:])
