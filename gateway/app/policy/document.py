"""The policy document: its shape, and validation that says where each problem is."""

from dataclasses import dataclass
from difflib import get_close_matches
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
)
from pydantic_core import ErrorDetails

from gateway.app.core.types import Action, Channel, InjectionProtection, ToolStatus, Trust
from gateway.app.policy.schemas import ValidationIssue
from gateway.app.policy.source import Path, Source, YamlSyntaxError, format_path, load

MAX_POLICY_BYTES = 64 * 1024
ON_ERROR_RULE = "on-error"
NO_MATCH_RULE = "no-rule-matched"
RESERVED_RULE_NAMES = frozenset({ON_ERROR_RULE, NO_MATCH_RULE})


class OnErrorAction(StrEnum):
    BLOCK = "block"
    MASK_LOCAL = "mask_local"


OnError = dict[ToolStatus, OnErrorAction]

# What the scalar `on_error: block` stands for.
BLOCK_UNTRUSTED_TOOLS: OnError = {
    ToolStatus.APPROVED: OnErrorAction.MASK_LOCAL,
    ToolStatus.TOLERATED: OnErrorAction.MASK_LOCAL,
    ToolStatus.UNAPPROVED: OnErrorAction.BLOCK,
    ToolStatus.UNKNOWN: OnErrorAction.BLOCK,
}


def _expand_on_error(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value == OnErrorAction.BLOCK:
        return BLOCK_UNTRUSTED_TOOLS
    if value == OnErrorAction.MASK_LOCAL:
        return dict.fromkeys(ToolStatus, OnErrorAction.MASK_LOCAL)
    raise ValueError("Use `block`, `mask_local`, or a map from tool status to one of them")


def _block_unlisted(value: OnError) -> OnError:
    return {status: value.get(status, OnErrorAction.BLOCK) for status in ToolStatus}


def _listed(value: Any) -> Any:
    return value if value is None or isinstance(value, list | tuple) else [value]


_Listed = BeforeValidator(_listed)
_Name = Annotated[str, Field(min_length=1, max_length=120)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class When(_Model):
    """Every key that is present must match. A list matches any of its values."""

    channel: Annotated[tuple[Channel, ...] | None, _Listed] = Field(default=None, min_length=1)
    data: Annotated[tuple[_Name, ...] | None, _Listed] = Field(default=None, min_length=1)
    tool_status: Annotated[tuple[ToolStatus, ...] | None, _Listed] = Field(
        default=None, min_length=1
    )
    tool: Annotated[tuple[_Name, ...] | None, _Listed] = Field(default=None, min_length=1)
    team: Annotated[tuple[_Name, ...] | None, _Listed] = Field(default=None, min_length=1)
    tainted: StrictBool | None = None
    side_effects: StrictBool | None = None
    destination: Annotated[tuple[Trust, ...] | None, _Listed] = Field(default=None, min_length=1)
    source: Annotated[tuple[Trust, ...] | None, _Listed] = Field(default=None, min_length=1)

    @property
    def matches_everything(self) -> bool:
        return all(getattr(self, name) is None for name in type(self).model_fields)


class Rule(_Model):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    when: When = When()
    action: Action
    suggest: Literal["approved_alternative"] | None = None


class PolicyDocument(_Model):
    version: Literal[1] = Field(description="The format of the file, not the saved version")
    on_error: Annotated[
        OnError, BeforeValidator(_expand_on_error), AfterValidator(_block_unlisted)
    ] = Field(default_factory=lambda: dict(BLOCK_UNTRUSTED_TOOLS))
    injection_protection: InjectionProtection = InjectionProtection.STANDARD
    rules: tuple[Rule, ...] = Field(min_length=1)


class PolicyInvalidError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        super().__init__(f"The policy has {len(issues)} validation issue(s)")
        self.issues = issues


@dataclass(frozen=True)
class Checked:
    """`document` is set when the structure is sound, even if `issues` lists other problems."""

    document: PolicyDocument | None
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def check(text: str, known_data_types: frozenset[str]) -> Checked:
    """Reading a policy is slow enough to hold up other requests: call this in a thread."""
    try:
        if len(text.encode("utf-8", "surrogatepass")) > MAX_POLICY_BYTES:
            raise YamlSyntaxError(
                f"The policy is larger than {MAX_POLICY_BYTES // 1024} KB. "
                "Remove rules or comments until it fits",
                None,
            )
        source = load(text)
    except YamlSyntaxError as exc:
        return Checked(
            None, (ValidationIssue(path=format_path(()), message=exc.message, line=exc.line),)
        )
    issues = [
        _issue(source, path, "This key appears twice; only the last value would count")
        for path in source.duplicate_keys
    ]
    try:
        document = PolicyDocument.model_validate(source.data)
    except ValidationError as exc:
        issues += [_issue(source, error["loc"], _message(error)) for error in exc.errors()]
        return Checked(None, _in_order(issues))
    issues += _rule_issues(document, source, known_data_types)
    return Checked(document, _in_order(issues))


def _in_order(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    return tuple(sorted(issues, key=lambda issue: issue.line or 0))


def _issue(source: Source, path: Path, message: str) -> ValidationIssue:
    found, line = source.locate(path)
    return ValidationIssue(path=format_path(found), message=message, line=line)


_MESSAGES = {
    "extra_forbidden": "Unknown key. Allowed here: {allowed}",
    "enum": "Must be {expected}",
    "literal_error": "Must be {expected}",
    "model_type": "Expected a map of keys and values",
    "dict_type": "Expected a map of keys and values",
    "tuple_type": "Expected a list",
    "too_short": "Must not be empty",
    "string_pattern_mismatch": "Use letters, digits, hyphens and underscores, starting with a "
    "letter or digit",
    "bool_type": "Must be true or false",
}


def _message(error: ErrorDetails) -> str:
    kind, path = error["type"], error["loc"]
    if kind == "missing":
        return f"`{path[-1]}` is required"
    template = _MESSAGES.get(kind)
    if template is None:
        return error["msg"].removeprefix("Value error, ")
    return template.format(
        expected=error.get("ctx", {}).get("expected"), allowed=", ".join(_keys_at(path))
    )


def _keys_at(path: Path) -> list[str]:
    """The keys allowed in the mapping that holds the last part of `path`."""
    model: type[BaseModel] = PolicyDocument if len(path) == 1 else Rule if len(path) == 3 else When
    return list(model.model_fields)


def _rule_issues(
    document: PolicyDocument, source: Source, known_data_types: frozenset[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    names: set[str] = set()
    catch_all: str | None = None
    for index, rule in enumerate(document.rules):
        here: Path = ("rules", index)
        if catch_all is not None:
            message = (
                f"This rule and any after it can never apply: `{catch_all}` above has no "
                "conditions, so it matches everything"
            )
            issues.append(_issue(source, here, message))
            break
        if rule.name in names:
            issues.append(_issue(source, (*here, "name"), f"Two rules are named `{rule.name}`"))
        if rule.name in RESERVED_RULE_NAMES:
            message = f"`{rule.name}` is reserved for decisions the engine makes itself"
            issues.append(_issue(source, (*here, "name"), message))
        names.add(rule.name)
        for position, data_type in enumerate(rule.when.data or ()):
            if data_type not in known_data_types:
                path: Path = (*here, "when", "data", position)
                issues.append(_issue(source, path, _unknown_type(data_type, known_data_types)))
        if rule.when.matches_everything:
            catch_all = rule.name
    return issues


def _unknown_type(data_type: str, known: frozenset[str]) -> str:
    guess = get_close_matches(data_type.upper(), known, n=1)
    if guess:
        return f"Unknown data type `{data_type}`; did you mean `{guess[0]}`?"
    return f"Unknown data type `{data_type}`. Known types: {', '.join(sorted(known))}"
