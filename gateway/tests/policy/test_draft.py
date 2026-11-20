from pathlib import Path
from typing import Any, cast

import pytest
from openai import APITimeoutError

from gateway.app.core.types import (
    Action,
    Channel,
    DataType,
    PolicyContext,
    ToolRef,
    ToolStatus,
)
from gateway.app.policy.document import PolicyDocument, Rule, check
from gateway.app.policy.draft import Vocabulary, draft_rule
from gateway.app.policy.evaluate import evaluate
from gateway.app.policy.schemas import DraftResult
from gateway.tests.doubles import FakeLLM

DEFAULT_POLICY = (Path(__file__).resolve().parents[3] / "policies" / "default.yaml").read_text(
    encoding="utf-8"
)
VOCABULARY = Vocabulary(
    data_types=DataType.BUILT_IN | {"PROJECT"},
    tools=[
        ToolRef(slug="chatterbox-ai", name="Chatterbox AI", status=ToolStatus.UNAPPROVED),
        ToolRef(slug="athena-assist", name="Athena Assist", status=ToolStatus.APPROVED),
    ],
    teams=["Sales", "Legal", "Customer Support"],
)


def _model_reply(**changes: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {
        "understood": True,
        "name": "Block contracts for Sales",
        "action": "block",
        "channel": ["prompt"],
        "data": ["CONTRACT"],
        "tool_status": ["tolerated"],
        "tool": [],
        "team": ["Sales"],
        "tainted": None,
        "side_effects": None,
        "destination": None,
        "source": None,
        "suggest_approved_alternative": True,
        "insert_before": "pii-and-client-data",
        "explanation": "Blocks contracts that Sales sends to tolerated tools.",
    }
    return reply | changes


def _unplaced(**changes: Any) -> dict[str, Any]:
    """A reply that names no rule to sit above and restricts nothing it is not told to."""
    reply = _model_reply(
        channel=[], data=[], tool_status=[], team=[], suggest_approved_alternative=False
    )
    return reply | {"insert_before": None} | changes


async def _draft(
    reply: dict[str, Any] | Exception,
    instruction: str = "Sales must not send contracts to tolerated tools",
    yaml_text: str = DEFAULT_POLICY,
) -> DraftResult:
    llm = FakeLLM(answers={"_ModelDraft": reply})
    return await draft_rule(instruction, yaml_text, llm=llm, vocabulary=VOCABULARY)


def _parsed(result: DraftResult) -> PolicyDocument:
    checked = check(result.yaml, VOCABULARY.data_types)
    assert checked.document is not None and checked.valid, checked.issues
    return checked.document


def _drafted(result: DraftResult) -> tuple[Rule, str]:
    """The drafted rule and the name of the rule right below it."""
    rules = _parsed(result).rules
    index = next(i for i, rule in enumerate(rules) if rule.name == result.rule_name)
    return rules[index], rules[index + 1].name


async def test_model_draft_is_merged_where_the_model_put_it() -> None:
    llm = FakeLLM(answers={"_ModelDraft": _model_reply()})
    result = await draft_rule(
        "Sales must not send contracts to tolerated tools",
        DEFAULT_POLICY,
        llm=llm,
        vocabulary=VOCABULARY,
    )
    rule, below = _drafted(result)
    assert result.rule_name == "block-contracts-for-sales"
    assert (rule.action, rule.when.data, rule.when.team) == (
        Action.BLOCK,
        ("CONTRACT",),
        ("Sales",),
    )
    assert rule.when.tainted is None and rule.suggest == "approved_alternative"
    assert below == "pii-and-client-data"
    assert result.explanation == (
        "Blocks contracts that Sales sends to tolerated tools. It sits above `pii-and-client-data`."
    )
    (call,) = llm.asked
    assert call.effort == "medium"
    for known in ("chatterbox-ai", "PROJECT", "Legal"):
        assert known in call.instructions
    assert "CUSTOM stands for every type the company defined itself" in call.instructions
    assert "Sales must not send contracts" in call.text and "secrets-never-leave" in call.text


async def test_a_rule_the_model_does_not_place_goes_above_the_first_less_strict_one() -> None:
    reply = _unplaced(
        name="Block source code to unapproved",
        channel=["prompt"],
        data=["SOURCE_CODE"],
        tool_status=["unapproved", "unknown"],
        explanation="Blocks source code in prompts to tools nobody approved.",
    )
    result = await _draft(reply)
    rule, below = _drafted(result)
    assert result.rule_name == "block-source-code-to-unapproved"
    assert rule.when.tool_status == (ToolStatus.UNAPPROVED, ToolStatus.UNKNOWN)
    assert rule.when.channel == (Channel.PROMPT,) and rule.suggest is None
    # The existing block rules stay above it, so they still win.
    assert below == "untrusted-destinations-get-placeholders"
    assert result.explanation == (
        "Blocks source code in prompts to tools nobody approved. It sits above "
        "`untrusted-destinations-get-placeholders`, the first rule that is less strict, "
        "so stricter rules win."
    )
    ctx = PolicyContext(
        channel=Channel.PROMPT,
        data_types=frozenset({"SOURCE_CODE"}),
        tool_status=ToolStatus.UNKNOWN,
    )
    assert evaluate(_parsed(result), ctx).rule == result.rule_name


@pytest.mark.parametrize(
    ("reply", "below"),
    [
        (
            _unplaced(name="warn-hr-to-tolerated", action="warn", data=["HR"]),
            "untrusted-destinations-get-placeholders",
        ),
        (_unplaced(name="redact-iban-everywhere", action="redact", data=["IBAN"]), "default"),
    ],
    ids=["warn", "redact"],
)
async def test_a_milder_rule_goes_further_down(reply: dict[str, Any], below: str) -> None:
    result = await _draft(reply)
    rule, next_rule = _drafted(result)
    assert rule.action.value == reply["action"] and next_rule == below


async def test_allow_goes_below_the_block_rules() -> None:
    reply = _unplaced(name="allow-source-code-for-legal", action="allow", team=["Legal"])
    result = await _draft(reply | {"data": ["SOURCE_CODE"], "tool_status": ["tolerated"]})
    rule, below = _drafted(result)
    assert rule.action is Action.ALLOW and rule.suggest is None
    assert below == "untrusted-destinations-get-placeholders"
    assert "below the block rules" in result.explanation


async def test_the_rest_of_the_policy_is_untouched() -> None:
    result = await _draft(_unplaced(name="redact-iban-everywhere", action="redact", data=["IBAN"]))
    added = [line for line in result.yaml.splitlines() if line not in DEFAULT_POLICY.splitlines()]
    assert added == ["  - name: redact-iban-everywhere", "      data: [IBAN]"]
    assert all(line in result.yaml.splitlines() for line in DEFAULT_POLICY.splitlines())


async def test_a_rule_for_custom_data_applies_to_every_company_type() -> None:
    reply = _unplaced(name="warn-custom-to-tolerated", action="warn", channel=["prompt"])
    result = await _draft(reply | {"data": ["CUSTOM"], "tool_status": ["tolerated"]})
    rule, _ = _drafted(result)
    assert (rule.action, rule.when.data) == (Action.WARN, ("CUSTOM",))
    ctx = PolicyContext(
        channel=Channel.PROMPT,
        data_types=frozenset({"PROJECT_CODE"}),
        tool_status=ToolStatus.TOLERATED,
    )
    assert evaluate(_parsed(result), ctx).rule == result.rule_name


async def test_named_tool_and_team() -> None:
    reply = _unplaced(name="Block contracts to Chatterbox AI from Customer Support")
    result = await _draft(
        reply | {"data": ["CONTRACT"], "tool": ["chatterbox-ai"], "team": ["Customer Support"]}
    )
    rule, _ = _drafted(result)
    assert rule.when.tool == ("chatterbox-ai",)
    assert rule.when.team == ("Customer Support",)
    assert rule.when.data == ("CONTRACT",)
    assert result.rule_name == "block-contracts-to-chatterbox-ai-from-customer-support"


async def test_a_second_draft_gets_a_new_name() -> None:
    reply = _unplaced(name="redact-iban-everywhere", action="redact", data=["IBAN"])
    first = await _draft(reply)
    second = await _draft(reply, yaml_text=first.yaml)
    assert second.rule_name == "redact-iban-everywhere-2"
    assert check(second.yaml, VOCABULARY.data_types).valid


async def test_model_may_decline() -> None:
    result = await _draft(_model_reply(understood=False, explanation="This needs two rules."))
    assert (result.rule_name, result.yaml) == (None, DEFAULT_POLICY)
    assert result.explanation == "This needs two rules."


@pytest.mark.parametrize(
    "reply",
    [
        _model_reply(data=["NOT_A_TYPE"]),
        _model_reply(name="!!!", team=[""]),
        cast(Exception, APITimeoutError(request=cast(Any, None))),
    ],
    ids=["unknown-data-type", "invalid-rule", "timeout"],
)
async def test_an_unusable_model_answer_drafts_nothing_and_says_so(
    reply: dict[str, Any] | Exception,
) -> None:
    result = await _draft(reply)
    assert (result.rule_name, result.yaml) == (None, DEFAULT_POLICY)
    assert result.explanation.startswith("The model did not return a rule that can be used.")


async def test_invalid_policy_is_not_drafted_into() -> None:
    llm = FakeLLM()
    result = await draft_rule(
        "Redact IBANs everywhere.", "version: 1\nrules: nope\n", llm=llm, vocabulary=VOCABULARY
    )
    assert result.rule_name is None and llm.asked == []
    assert "validation errors" in result.explanation
