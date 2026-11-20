"""Every rule of the default policy, and what happens when a detector fails."""

from pathlib import Path
from typing import Any

import pytest

from gateway.app.core.types import (
    Action,
    Channel,
    DataType,
    PolicyContext,
    ToolRef,
    ToolStatus,
    Trust,
)
from gateway.app.policy.document import NO_MATCH_RULE, ON_ERROR_RULE, PolicyDocument, check
from gateway.app.policy.evaluate import evaluate, is_milder_at, with_tool_status

DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "policies" / "default.yaml"
PII = ("PERSON", "AFM", "IBAN")


def _policy(text: str, known: frozenset[str] = DataType.BUILT_IN) -> PolicyDocument:
    checked = check(text, known)
    assert checked.document is not None and checked.valid, checked.issues
    return checked.document


@pytest.fixture(scope="module")
def default_policy() -> PolicyDocument:
    return _policy(DEFAULT_POLICY.read_text(encoding="utf-8"))


def _ctx(
    channel: Channel = Channel.PROMPT,
    data: tuple[str, ...] = (),
    status: ToolStatus | None = None,
    **more: Any,
) -> PolicyContext:
    return PolicyContext(channel=channel, data_types=frozenset(data), tool_status=status, **more)


PROMPT, CALL, RESULT = Channel.PROMPT, Channel.TOOL_CALL, Channel.TOOL_RESULT
APPROVED, TOLERATED = ToolStatus.APPROVED, ToolStatus.TOLERATED
UNAPPROVED, UNKNOWN = ToolStatus.UNAPPROVED, ToolStatus.UNKNOWN

# (context, rule that fires, action)
CASES: list[tuple[PolicyContext, str, Action]] = [
    # Secrets are blocked on every channel and for every tool.
    (_ctx(PROMPT, ("SECRET",), APPROVED), "secrets-never-leave", Action.BLOCK),
    (_ctx(PROMPT, ("SECRET", "PERSON"), UNKNOWN), "secrets-never-leave", Action.BLOCK),
    (_ctx(RESULT, ("SECRET",)), "secrets-never-leave", Action.BLOCK),
    (_ctx(CALL, ("SECRET",), destination=Trust.TRUSTED), "secrets-never-leave", Action.BLOCK),
    # The agent, after reading untrusted content, may not send or change anything.
    (
        _ctx(CALL, PII, tainted=True, side_effects=True, destination=Trust.UNTRUSTED),
        "tainted-agent-side-effects",
        Action.BLOCK,
    ),
    (
        _ctx(CALL, tainted=True, side_effects=True, destination=Trust.TRUSTED),
        "tainted-agent-side-effects",
        Action.BLOCK,
    ),
    # Without the taint, an outside destination gets placeholders only.
    (
        _ctx(CALL, PII, side_effects=True, destination=Trust.UNTRUSTED),
        "untrusted-destinations-get-placeholders",
        Action.REDACT,
    ),
    (
        _ctx(CALL, tainted=True, side_effects=False, destination=Trust.UNTRUSTED),
        "untrusted-destinations-get-placeholders",
        Action.REDACT,
    ),
    # A trusted destination receives real values.
    (_ctx(CALL, PII, side_effects=True, destination=Trust.TRUSTED), "default", Action.ALLOW),
    # What a tool returns is masked before the agent's model sees it.
    (
        _ctx(RESULT, ("CLIENT", "EMAIL"), source=Trust.TRUSTED),
        "agent-model-sees-placeholders",
        Action.REDACT,
    ),
    (
        _ctx(RESULT, ("PERSON",), source=Trust.UNTRUSTED),
        "agent-model-sees-placeholders",
        Action.REDACT,
    ),
    (_ctx(RESULT, (), source=Trust.UNTRUSTED), "default", Action.ALLOW),
    # The in-house agent's model holds placeholders although its tool is approved.
    (
        _ctx(PROMPT, ("CLIENT", "IBAN"), APPROVED, tool="company-assistant"),
        "agent-prompts-use-placeholders",
        Action.REDACT,
    ),
    (_ctx(PROMPT, (), APPROVED, tool="company-assistant"), "default", Action.ALLOW),
    (_ctx(PROMPT, PII, APPROVED, tool="athena-assist"), "default", Action.ALLOW),
    # Contracts never reach a tool nobody approved, whatever else is in the prompt.
    (_ctx(PROMPT, ("CONTRACT",), UNAPPROVED), "contract-to-unapproved", Action.BLOCK),
    (_ctx(PROMPT, ("CONTRACT", "PERSON"), UNKNOWN), "contract-to-unapproved", Action.BLOCK),
    (_ctx(PROMPT, ("CONTRACT",), TOLERATED), "default", Action.ALLOW),
    (_ctx(PROMPT, ("CONTRACT",), APPROVED), "default", Action.ALLOW),
    # Scene 1: a name, an AFM and an IBAN to an unapproved tool.
    (_ctx(PROMPT, PII, UNAPPROVED), "pii-and-client-data", Action.REDACT),
    (_ctx(PROMPT, ("EMAIL",), TOLERATED), "pii-and-client-data", Action.REDACT),
    (_ctx(PROMPT, ("CLIENT",), UNKNOWN), "pii-and-client-data", Action.REDACT),
    (
        _ctx(PROMPT, ("CARD", "ADDRESS"), UNAPPROVED, team="Sales"),
        "pii-and-client-data",
        Action.REDACT,
    ),
    # Marked or sensitive documents need the user's confirmation.
    (
        _ctx(PROMPT, ("CONFIDENTIAL_MARKER",), TOLERATED),
        "marked-or-sensitive-category",
        Action.WARN,
    ),
    (_ctx(PROMPT, ("HR",), UNKNOWN), "marked-or-sensitive-category", Action.WARN),
    (_ctx(PROMPT, ("FINANCIAL",), UNAPPROVED), "marked-or-sensitive-category", Action.WARN),
    (
        _ctx(PROMPT, ("HEALTH", "CLIENT_CONFIDENTIAL"), TOLERATED),
        "marked-or-sensitive-category",
        Action.WARN,
    ),
    # PII comes first in the file, so it wins over the warning.
    (_ctx(PROMPT, ("HR", "PERSON"), TOLERATED), "pii-and-client-data", Action.REDACT),
    (_ctx(PROMPT, ("SOURCE_CODE",), TOLERATED), "source-code-warning", Action.WARN),
    (_ctx(PROMPT, ("SOURCE_CODE",), UNAPPROVED), "source-code-warning", Action.WARN),
    (_ctx(PROMPT, ("SOURCE_CODE",), UNKNOWN), "default", Action.ALLOW),
    (_ctx(PROMPT, ("SOURCE_CODE",), APPROVED), "default", Action.ALLOW),
    # A type the company defined itself is masked wherever personal and client data are.
    (_ctx(PROMPT, ("PROJECT_CODE",), UNAPPROVED), "pii-and-client-data", Action.REDACT),
    (_ctx(PROMPT, ("PROJECT_CODE", "ORG"), TOLERATED), "pii-and-client-data", Action.REDACT),
    (_ctx(PROMPT, ("BOARD_MINUTES",), UNKNOWN), "pii-and-client-data", Action.REDACT),
    (
        _ctx(PROMPT, ("PROJECT_CODE",), APPROVED, tool="company-assistant"),
        "agent-prompts-use-placeholders",
        Action.REDACT,
    ),
    (
        _ctx(RESULT, ("PROJECT_CODE",), source=Trust.TRUSTED),
        "agent-model-sees-placeholders",
        Action.REDACT,
    ),
    (_ctx(PROMPT, ("PROJECT_CODE",), APPROVED, tool="athena-assist"), "default", Action.ALLOW),
    (_ctx(PROMPT, ("PROJECT_CODE", "SECRET"), UNAPPROVED), "secrets-never-leave", Action.BLOCK),
    (_ctx(PROMPT, ("PROJECT_CODE", "CONTRACT"), UNKNOWN), "contract-to-unapproved", Action.BLOCK),
    # Nothing sensitive, or built-in types no rule names: organisations and places stay.
    (_ctx(PROMPT, (), UNAPPROVED), "default", Action.ALLOW),
    (_ctx(PROMPT, ("ORG", "LOCATION"), UNKNOWN), "default", Action.ALLOW),
    # A detector failed: refuse unless the tool is approved.
    (_ctx(PROMPT, PII, UNAPPROVED, detector_error=True), ON_ERROR_RULE, Action.BLOCK),
    (_ctx(PROMPT, (), UNKNOWN, detector_error=True), ON_ERROR_RULE, Action.BLOCK),
    (_ctx(PROMPT, (), TOLERATED, detector_error=True), ON_ERROR_RULE, Action.BLOCK),
    # For an approved tool the rules run on what the local tiers found.
    (_ctx(PROMPT, PII, APPROVED, detector_error=True), "default", Action.ALLOW),
    (_ctx(PROMPT, ("SECRET",), APPROVED, detector_error=True), "secrets-never-leave", Action.BLOCK),
    (
        _ctx(PROMPT, ("CLIENT",), APPROVED, tool="company-assistant", detector_error=True),
        "agent-prompts-use-placeholders",
        Action.REDACT,
    ),
    # Agent channels have no tool status and follow `approved`.
    (
        _ctx(RESULT, ("PERSON",), source=Trust.UNTRUSTED, detector_error=True),
        "agent-model-sees-placeholders",
        Action.REDACT,
    ),
]


@pytest.mark.parametrize(("ctx", "rule", "action"), CASES)
def test_default_policy(
    default_policy: PolicyDocument, ctx: PolicyContext, rule: str, action: Action
) -> None:
    outcome = evaluate(default_policy, ctx)
    assert (outcome.rule, outcome.action) == (rule, action)


def test_table_covers_every_rule_of_the_default_policy(default_policy: PolicyDocument) -> None:
    covered = {rule for _, rule, _ in CASES}
    assert {rule.name for rule in default_policy.rules} <= covered
    assert ON_ERROR_RULE in covered


def test_matched_types_are_the_ones_the_rule_names(default_policy: PolicyDocument) -> None:
    outcome = evaluate(default_policy, _ctx(PROMPT, ("ORG", "IBAN", "PERSON"), UNAPPROVED))
    assert outcome.matched_types == ("PERSON", "IBAN")


def test_custom_stands_for_every_type_that_is_not_built_in(default_policy: PolicyDocument) -> None:
    outcome = evaluate(default_policy, _ctx(PROMPT, ("TICKET", "IBAN", "PROJECT_CODE"), UNKNOWN))
    # The found types the rule asked for, in the rule's order; `CUSTOM` comes last in its list.
    assert outcome.matched_types == ("IBAN", "PROJECT_CODE", "TICKET")
    only_custom = _policy(
        "version: 1\nrules:\n"
        "  - name: ours\n    when: { data: [CUSTOM] }\n    action: warn\n"
        "  - name: default\n    action: allow\n"
    )
    assert evaluate(only_custom, _ctx(PROMPT, ("PROJECT_CODE",), APPROVED)).rule == "ours"
    for built_in in sorted(DataType.BUILT_IN - {DataType.CUSTOM}):
        assert evaluate(only_custom, _ctx(PROMPT, (built_in,), APPROVED)).rule == "default"
    assert evaluate(only_custom, _ctx(PROMPT, (), APPROVED)).rule == "default"
    # A company may call one of its own types CUSTOM; the rule then names it like any other.
    assert evaluate(only_custom, _ctx(PROMPT, ("CUSTOM",), APPROVED)).matched_types == ("CUSTOM",)


def test_a_rule_can_still_name_one_custom_type() -> None:
    policy = _policy(
        "version: 1\nrules:\n"
        "  - name: no-project-codes\n    when: { data: [PROJECT_CODE] }\n    action: block\n"
        "  - name: ours\n    when: { data: [CUSTOM] }\n    action: redact\n"
        "  - name: default\n    action: allow\n",
        known=DataType.BUILT_IN | {"PROJECT_CODE"},
    )
    named = evaluate(policy, _ctx(PROMPT, ("PROJECT_CODE", "TICKET"), UNKNOWN))
    assert (named.rule, named.matched_types) == ("no-project-codes", ("PROJECT_CODE",))
    other = evaluate(policy, _ctx(PROMPT, ("TICKET",), UNKNOWN))
    assert (other.rule, other.matched_types) == ("ours", ("TICKET",))


def test_scalar_on_error_masks_locally_for_tolerated_tools() -> None:
    policy = _policy(
        "version: 1\non_error: block\nrules:\n"
        "  - name: pii\n    when: { data: [IBAN] }\n    action: redact\n"
        "  - name: default\n    action: allow\n"
    )
    tolerated = evaluate(policy, _ctx(PROMPT, ("IBAN",), TOLERATED, detector_error=True))
    assert (tolerated.rule, tolerated.action) == ("pii", Action.REDACT)
    assert tolerated.local_tiers_only
    unknown = evaluate(policy, _ctx(PROMPT, ("IBAN",), UNKNOWN, detector_error=True))
    assert (unknown.rule, unknown.action) == (ON_ERROR_RULE, Action.BLOCK)


def test_conditions_on_tool_team_and_source() -> None:
    policy = _policy(
        "version: 1\nrules:\n"
        "  - name: legal-only\n    when: { team: [Legal, Finance], tool: Athena-Assist }\n"
        "    action: warn\n"
        "  - name: web-content\n    when: { channel: tool_result, source: untrusted }\n"
        "    action: redact\n"
    )
    by_team = evaluate(policy, _ctx(PROMPT, (), APPROVED, team="legal", tool="athena-assist"))
    assert by_team.rule == "legal-only"
    other_team = evaluate(policy, _ctx(PROMPT, (), APPROVED, team="Sales", tool="athena-assist"))
    no_team = evaluate(policy, _ctx(PROMPT, (), APPROVED, tool="athena-assist"))
    assert other_team.rule == no_team.rule == NO_MATCH_RULE
    assert other_team.action is Action.ALLOW
    assert evaluate(policy, _ctx(RESULT, source=Trust.UNTRUSTED)).rule == "web-content"
    assert evaluate(policy, _ctx(RESULT, source=Trust.TRUSTED)).rule == NO_MATCH_RULE


def test_an_alternative_must_get_a_milder_decision(default_policy: PolicyDocument) -> None:
    athena = ToolRef(slug="athena-assist", name="Athena Assist", status=APPROVED)
    contract = _ctx(PROMPT, ("CONTRACT",), UNAPPROVED, tool="chatterbox-ai")
    secret = _ctx(PROMPT, ("SECRET",), UNAPPROVED, tool="chatterbox-ai")
    assert is_milder_at(default_policy, contract, athena, Action.BLOCK)
    # A secret is blocked everywhere, so no other tool would help.
    assert not is_milder_at(default_policy, secret, athena, Action.BLOCK)


def test_a_prompt_without_a_status_counts_as_unknown(default_policy: PolicyDocument) -> None:
    bare = _ctx(PROMPT, PII)
    assert with_tool_status(bare).tool_status is UNKNOWN
    assert with_tool_status(bare, TOLERATED).tool_status is TOLERATED
    assert with_tool_status(_ctx(PROMPT, PII, APPROVED), UNKNOWN).tool_status is APPROVED
    # Agent channels have no AI tool, so they stay without one.
    assert with_tool_status(_ctx(RESULT, PII)).tool_status is None
    assert evaluate(default_policy, with_tool_status(bare)).action is Action.REDACT
