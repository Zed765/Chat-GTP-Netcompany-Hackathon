from pathlib import Path

import pytest

from gateway.app.core.types import DataType, InjectionProtection, ToolStatus
from gateway.app.policy.document import MAX_POLICY_BYTES, OnErrorAction, check

DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "policies" / "default.yaml"
KNOWN = DataType.BUILT_IN

MINIMAL = """\
version: 1
rules:
  - name: default
    action: allow
"""


def test_default_policy_is_valid() -> None:
    checked = check(DEFAULT_POLICY.read_text(encoding="utf-8"), KNOWN)
    assert checked.valid, checked.issues
    assert checked.document is not None
    assert checked.document.injection_protection is InjectionProtection.STANDARD
    assert checked.document.on_error[ToolStatus.APPROVED] is OnErrorAction.MASK_LOCAL
    assert checked.document.on_error[ToolStatus.TOLERATED] is OnErrorAction.BLOCK


def test_the_plan_example_is_valid() -> None:
    text = """\
version: 1
on_error: block
injection_protection: standard
rules:
  - name: secrets-never-leave
    when: { data: [SECRET] }
    action: block
  - name: contract-to-unapproved
    when:
      tool_status: [unapproved, unknown]
      data: [CONTRACT]
    action: block
    suggest: approved_alternative
  - name: tainted-agent-side-effects
    when: { channel: tool_call, side_effects: true, tainted: true }
    action: block
  - name: default
    action: allow
"""
    checked = check(text, KNOWN)
    assert checked.valid, checked.issues
    assert checked.document is not None
    # The scalar form blocks tools nobody approved and falls back to local masking otherwise.
    assert checked.document.on_error == {
        ToolStatus.APPROVED: OnErrorAction.MASK_LOCAL,
        ToolStatus.TOLERATED: OnErrorAction.MASK_LOCAL,
        ToolStatus.UNAPPROVED: OnErrorAction.BLOCK,
        ToolStatus.UNKNOWN: OnErrorAction.BLOCK,
    }
    tainted = checked.document.rules[2].when
    assert tainted.tainted is True and tainted.side_effects is True


def test_on_error_map_blocks_the_statuses_it_leaves_out() -> None:
    checked = check(MINIMAL.replace("rules:", "on_error: { approved: mask_local }\nrules:"), KNOWN)
    assert checked.document is not None
    assert checked.document.on_error[ToolStatus.APPROVED] is OnErrorAction.MASK_LOCAL
    assert checked.document.on_error[ToolStatus.UNKNOWN] is OnErrorAction.BLOCK


def test_off_is_a_protection_level_not_a_boolean() -> None:
    checked = check(MINIMAL.replace("rules:", "injection_protection: off\nrules:"), KNOWN)
    assert checked.valid, checked.issues
    assert checked.document is not None
    assert checked.document.injection_protection is InjectionProtection.OFF


def test_scalars_and_lists_mean_the_same() -> None:
    scalar = check(
        MINIMAL.replace(
            "rules:", "rules:\n  - name: a\n    when: { data: IBAN }\n    action: redact"
        ),
        KNOWN,
    )
    listed = check(
        MINIMAL.replace(
            "rules:", "rules:\n  - name: a\n    when: { data: [IBAN] }\n    action: redact"
        ),
        KNOWN,
    )
    assert scalar.valid and scalar.document == listed.document


def _rules(body: str) -> str:
    return f"version: 1\nrules:\n{body}  - name: default\n    action: allow\n"


@pytest.mark.parametrize(
    ("text", "path", "line", "message"),
    [
        pytest.param(
            _rules("  - name: a\n    when: { dta: [IBAN] }\n    action: redact\n"),
            "rules[0].when.dta",
            4,
            "Unknown key. Allowed here: channel, data",
            id="unknown-condition",
        ),
        pytest.param(
            _rules("  - name: a\n    when: { data: [IBAN] }\n    action: mask\n"),
            "rules[0].action",
            5,
            "Must be 'allow', 'redact', 'warn' or 'block'",
            id="unknown-action",
        ),
        pytest.param(
            _rules("  - name: a\n    when:\n      data: [IBAN, PERSN]\n    action: redact\n"),
            "rules[0].when.data[1]",
            5,
            "Unknown data type `PERSN`; did you mean `PERSON`?",
            id="unknown-data-type",
        ),
        pytest.param(
            _rules("  - name: a\n    when: { data: [] }\n    action: redact\n"),
            "rules[0].when.data",
            4,
            "Must not be empty",
            id="empty-list",
        ),
        pytest.param(
            _rules("  - name: a\n    when: { tool_status: banned }\n    action: block\n"),
            "rules[0].when.tool_status",
            4,
            "Must be 'approved', 'tolerated', 'unapproved' or 'unknown'",
            id="unknown-status",
        ),
        pytest.param(
            _rules("  - name: a\n    when: { tainted: maybe }\n    action: block\n"),
            "rules[0].when.tainted",
            4,
            "Must be true or false",
            id="not-a-boolean",
        ),
        pytest.param(
            _rules("  - name: a\n    when: { data: [IBAN] }\n"),
            "rules[0]",
            3,
            "`action` is required",
            id="missing-action",
        ),
        pytest.param(
            "version: 1\n",
            "(document)",
            1,
            "`rules` is required",
            id="missing-rules",
        ),
        pytest.param(
            _rules("  - name: twice\n    action: redact\n    when: { data: [IBAN] }\n")
            .replace("name: default", "name: twice")
            .replace("action: allow", "action: allow\n    when: { channel: prompt }"),
            "rules[1].name",
            6,
            "Two rules are named `twice`",
            id="duplicate-name",
        ),
        pytest.param(
            "version: 1\nrules:\n  - name: default\n    action: allow\n"
            "  - name: late\n    when: { data: [IBAN] }\n    action: block\n",
            "rules[1]",
            5,
            "can never apply: `default` above has no conditions",
            id="unreachable-rule",
        ),
        pytest.param(
            _rules("  - name: on-error\n    when: { data: [IBAN] }\n    action: block\n"),
            "rules[0].name",
            3,
            "`on-error` is reserved",
            id="reserved-name",
        ),
        pytest.param(
            _rules("  - name: bad name!\n    when: { data: [IBAN] }\n    action: block\n"),
            "rules[0].name",
            3,
            "Use letters, digits, hyphens and underscores",
            id="bad-name",
        ),
        pytest.param(
            MINIMAL.replace("rules:", "on_error: allow\nrules:"),
            "on_error",
            2,
            "Use `block`, `mask_local`, or a map",
            id="bad-on-error",
        ),
        pytest.param(
            MINIMAL.replace("rules:", "on_error:\n  aproved: block\nrules:"),
            "on_error.aproved",
            3,
            "Must be 'approved', 'tolerated', 'unapproved' or 'unknown'",
            id="bad-on-error-status",
        ),
        pytest.param(
            MINIMAL.replace("rules:", "injection_protection: paranoid\nrules:"),
            "injection_protection",
            2,
            "Must be 'off', 'standard' or 'detailed'",
            id="bad-protection-level",
        ),
        pytest.param(
            MINIMAL.replace("version: 1", "version: 2"),
            "version",
            1,
            "Must be 1",
            id="bad-version",
        ),
        pytest.param(
            MINIMAL + "version: 1\n",
            "version",
            5,
            "appears twice",
            id="duplicate-key",
        ),
        pytest.param(
            "version: 1\nrules:\n  - name: a\n    when: { data: [IBAN }\n",
            "(document)",
            4,
            "This is not valid YAML",
            id="syntax-error",
        ),
        pytest.param("- just\n- a list\n", "(document)", 1, "Expected a map", id="not-a-map"),
    ],
)
def test_issue_says_where_and_what(text: str, path: str, line: int, message: str) -> None:
    checked = check(text, KNOWN)
    assert not checked.valid
    found = [(issue.path, issue.line) for issue in checked.issues]
    assert (path, line) in found, checked.issues
    issue = next(issue for issue in checked.issues if issue.path == path)
    assert message in issue.message


def test_every_problem_is_reported_at_once_in_line_order() -> None:
    text = _rules(
        "  - name: a\n    when: { data: [NOPE_1] }\n    action: redact\n"
        "  - name: a\n    when: { data: [NOPE_2] }\n    action: redact\n"
    )
    issues = check(text, KNOWN).issues
    assert [issue.path for issue in issues] == [
        "rules[0].when.data[0]",
        "rules[1].name",
        "rules[1].when.data[0]",
    ]
    assert [issue.line for issue in issues] == sorted(issue.line or 0 for issue in issues)


def test_custom_data_type_is_valid_once_the_store_knows_it() -> None:
    text = _rules("  - name: projects\n    when: { data: [PROJECT] }\n    action: redact\n")
    assert not check(text, KNOWN).valid
    assert check(text, KNOWN | {"PROJECT"}).valid


def test_custom_is_a_built_in_name_for_the_types_a_company_adds() -> None:
    text = _rules("  - name: ours\n    when: { data: [CUSTOM, IBAN] }\n    action: redact\n")
    assert check(text, KNOWN).valid
    misspelt = check(text.replace("CUSTOM", "CUSTM"), KNOWN)
    assert "did you mean `CUSTOM`?" in misspelt.issues[0].message


def test_unknown_data_type_still_gives_a_document_to_enforce() -> None:
    text = _rules("  - name: projects\n    when: { data: [PROJECT] }\n    action: redact\n")
    checked = check(text, KNOWN)
    assert checked.document is not None and not checked.valid


def _nested_aliases(levels: int) -> str:
    """Each level repeats the one before nine times: a few hundred bytes, 9**levels nodes."""
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x]"]
    lines += [
        f"a{level}: &a{level} [{', '.join([f'*a{level - 1}'] * 9)}]"
        for level in range(1, levels + 1)
    ]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("text", "line", "what"),
    [
        pytest.param(_nested_aliases(40), 1, "anchor", id="nested-aliases"),
        pytest.param(MINIMAL + "also: *missing\n", 5, "alias", id="alias"),
        pytest.param(
            _rules("  - &shared\n    name: a\n    when: { data: [IBAN] }\n    action: redact\n"),
            3,
            "anchor",
            id="anchor-on-a-rule",
        ),
        pytest.param(
            "defaults: &defaults { action: allow }\n"
            "version: 1\nrules:\n  - name: default\n    <<: *defaults\n",
            1,
            "anchor",
            id="merge-key",
        ),
    ],
)
def test_anchors_and_aliases_are_refused_where_they_first_appear(
    text: str, line: int, what: str
) -> None:
    checked = check(text, KNOWN)
    assert checked.document is None
    assert [(issue.path, issue.line) for issue in checked.issues] == [("(document)", line)]
    assert f"an {what}" in checked.issues[0].message
    assert "Anchors and aliases" in checked.issues[0].message


def test_a_policy_over_the_size_limit_is_refused_unread() -> None:
    padding = "# a comment that makes the file longer\n"
    fits = MINIMAL + padding * ((MAX_POLICY_BYTES - len(MINIMAL)) // len(padding))
    assert check(fits, KNOWN).valid
    checked = check(fits + padding, KNOWN)
    assert checked.document is None
    assert [issue.message for issue in checked.issues] == [
        "The policy is larger than 64 KB. Remove rules or comments until it fits"
    ]
    # Greek comments take two bytes a letter: the limit counts bytes, not characters.
    assert not check(MINIMAL + "# πολιτική\n" * 4000, KNOWN).valid


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[" * 5000, id="flow-nesting"),
        pytest.param("{a: " * 5000, id="map-nesting"),
        pytest.param("- " * 5000, id="list-nesting"),
        pytest.param("version: 1\nnote: \x00\n", id="control-character"),
        pytest.param("version: 1\nnote: \ud800\n", id="lone-surrogate"),
    ],
)
def test_text_that_cannot_be_read_is_an_issue_not_an_error(text: str) -> None:
    checked = check(text, KNOWN)
    assert checked.document is None
    assert [issue.path for issue in checked.issues] == ["(document)"]
    assert "not valid YAML" in checked.issues[0].message
