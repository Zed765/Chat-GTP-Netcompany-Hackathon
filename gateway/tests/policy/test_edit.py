from pathlib import Path

from gateway.app.core.types import Action, DataType, InjectionProtection
from gateway.app.policy.document import PolicyDocument, Rule, When, check
from gateway.app.policy.edit import with_injection_protection, with_rule
from gateway.app.policy.source import load

DEFAULT_POLICY = (Path(__file__).resolve().parents[3] / "policies" / "default.yaml").read_text(
    encoding="utf-8"
)
NEW_RULE = Rule(name="block-code", when=When(data=("SOURCE_CODE",)), action=Action.BLOCK)


def _document(text: str) -> PolicyDocument:
    checked = check(text, DataType.BUILT_IN)
    assert checked.document is not None and checked.valid, checked.issues
    return checked.document


def _changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    pairs = zip(before.splitlines(), after.splitlines(), strict=True)
    return [(old, new) for old, new in pairs if old != new]


def test_protection_level_changes_one_line_and_keeps_its_comment() -> None:
    text = DEFAULT_POLICY.replace(
        "injection_protection: standard", "injection_protection: standard  # agreed with the ADMIN"
    )
    edited = with_injection_protection(text, _document(text), InjectionProtection.OFF)
    assert _changed_lines(text, edited) == [
        (
            "injection_protection: standard  # agreed with the ADMIN",
            "injection_protection: off  # agreed with the ADMIN",
        )
    ]
    assert _document(edited).injection_protection is InjectionProtection.OFF


def test_protection_level_is_added_when_the_file_leaves_it_out() -> None:
    text = "# my policy\nversion: 1\nrules:\n  - name: default  # everything\n    action: allow\n"
    edited = with_injection_protection(text, _document(text), InjectionProtection.DETAILED)
    assert _document(edited).injection_protection is InjectionProtection.DETAILED
    assert "# my policy" in edited and "# everything" in edited


def test_flow_style_policy_is_rewritten_rather_than_broken() -> None:
    text = "{version: 1, injection_protection: standard, rules: [{name: default, action: allow}]}"
    document = _document(text)
    edited = with_injection_protection(text, document, InjectionProtection.OFF)
    assert _document(edited) == document.model_copy(
        update={"injection_protection": InjectionProtection.OFF}
    )
    with_new_rule = with_rule(text, load(text), document, NEW_RULE, 0)
    assert [rule.name for rule in _document(with_new_rule).rules] == ["block-code", "default"]


def test_rule_goes_above_the_comment_of_the_rule_it_precedes() -> None:
    document = _document(DEFAULT_POLICY)
    index = [rule.name for rule in document.rules].index("agent-prompts-use-placeholders")
    edited = with_rule(DEFAULT_POLICY, load(DEFAULT_POLICY), document, NEW_RULE, index)
    names = [rule.name for rule in _document(edited).rules]
    assert names[index : index + 2] == ["block-code", "agent-prompts-use-placeholders"]
    lines = edited.splitlines()
    rule = lines.index("  - name: agent-prompts-use-placeholders")
    assert lines[rule - 1].startswith("  # The in-house agent's model only ever holds")
    assert lines[rule - 3 : rule - 1] == ["    action: block", ""]
    # Nothing else moved: removing the new block gives back the original text.
    block = "  - name: block-code\n    when:\n      data: [SOURCE_CODE]\n    action: block\n\n"
    assert edited.replace(block, "") == DEFAULT_POLICY


def test_rule_can_be_added_after_the_last_one() -> None:
    text = "version: 1\nrules:\n  - name: pii\n    when: { data: [IBAN] }\n    action: redact"
    document = _document(text)
    edited = with_rule(text, load(text), document, NEW_RULE, 1)
    assert (
        edited
        == text
        + "\n  - name: block-code\n    when:\n      data: [SOURCE_CODE]\n    action: block\n"
    )


def test_compact_layout_stays_compact() -> None:
    text = (
        "version: 1\nrules:\n"
        "  - name: pii\n    when: { data: [IBAN] }\n    action: redact\n"
        "  - name: default\n    action: allow\n"
    )
    edited = with_rule(text, load(text), _document(text), NEW_RULE, 1)
    assert "\n\n" not in edited
    assert [rule.name for rule in _document(edited).rules] == ["pii", "block-code", "default"]
