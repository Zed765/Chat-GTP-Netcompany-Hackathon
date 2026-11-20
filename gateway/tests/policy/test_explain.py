from pathlib import Path
from typing import Any

import pytest

from gateway.app.core.types import (
    Action,
    Channel,
    DataType,
    Explanation,
    FoundItem,
    PolicyContext,
    Store,
    Tier,
    ToolRef,
    ToolStatus,
    Trust,
)
from gateway.app.policy.document import PolicyDocument, check
from gateway.app.policy.evaluate import evaluate
from gateway.app.policy.explain import explain

DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "policies" / "default.yaml"
ATHENA = ToolRef(slug="athena-assist", name="Athena Assist", status=ToolStatus.APPROVED)
CHATTERBOX = ToolRef(slug="chatterbox-ai", name="Chatterbox AI", status=ToolStatus.UNAPPROVED)
DRAFTPILOT = ToolRef(slug="draftpilot", name="DraftPilot", status=ToolStatus.TOLERATED)


@pytest.fixture(scope="module")
def policy() -> PolicyDocument:
    document = check(DEFAULT_POLICY.read_text(encoding="utf-8"), DataType.BUILT_IN).document
    assert document is not None
    return document


def _found(data_type: str, count: int = 1, tier: Tier = Tier.T0, **more: Any) -> FoundItem:
    return FoundItem(data_type=data_type, count=count, tier=tier, **more)


def _explain(
    policy: PolicyDocument,
    found: list[FoundItem],
    tool: ToolRef | None = None,
    alternatives: tuple[ToolRef, ...] = (),
    channel: Channel = Channel.PROMPT,
    **context: Any,
) -> Explanation:
    ctx = PolicyContext(
        channel=channel,
        data_types=frozenset(item.data_type for item in found),
        tool=tool.slug if tool else context.pop("tool_name", None),
        tool_status=tool.status if tool else None,
        **context,
    )
    return explain(ctx, found, evaluate(policy, ctx), tool, alternatives)


def test_scene_one_says_what_was_found_and_done(policy: PolicyDocument) -> None:
    found = [_found("PERSON", 2, Tier.T1), _found("AFM"), _found("IBAN")]
    explanation = _explain(policy, found, CHATTERBOX)
    assert explanation.summary == (
        "The prompt to Chatterbox AI (an unapproved tool) contained 2 person names, "
        "1 tax number (AFM) and 1 IBAN; each value was replaced with a placeholder before "
        "sending and restored in the answer."
    )
    assert explanation.rule == "pii-and-client-data"
    assert explanation.action is Action.REDACT
    assert explanation.found == tuple(found)
    assert explanation.advice == "Nothing more is needed: the AI tool saw placeholders only."


def test_block_names_the_cause_the_document_and_an_approved_tool(policy: PolicyDocument) -> None:
    found = [
        _found("PERSON", 2, Tier.T1),
        _found("CONTRACT", tier=Tier.T2, match_label="MSA Helios", store=Store.FINGERPRINTS),
    ]
    explanation = _explain(policy, found, CHATTERBOX, (ATHENA,))
    assert explanation.summary == (
        "The prompt to Chatterbox AI (an unapproved tool) contained text from the protected "
        'document "MSA Helios" (a contract) and 2 person names; because of the contract text, '
        "it was blocked and nothing was sent."
    )
    assert explanation.advice == (
        "Use Athena Assist for this, or remove the contract text and send again."
    )
    assert explanation.alternatives == (ATHENA,)


def test_category_without_a_document_only_resembles(policy: PolicyDocument) -> None:
    explanation = _explain(policy, [_found("CONTRACT", tier=Tier.T2)], CHATTERBOX)
    assert "contained text that looks like a contract;" in explanation.summary
    assert explanation.advice == "Remove the contract text and send again."


def test_secret_in_encoded_text(policy: PolicyDocument) -> None:
    found = [_found("EMAIL"), _found("SECRET", encoded=True)]
    explanation = _explain(policy, found, ATHENA)
    assert explanation.summary == (
        "The prompt to Athena Assist (an approved tool) contained 1 secret in encoded text and "
        "1 email address; because of the secret, it was blocked and nothing was sent."
    )
    assert explanation.advice is not None and explanation.advice.startswith("Remove the secret")


def test_warning_offers_confirmation_and_an_alternative(policy: PolicyDocument) -> None:
    explanation = _explain(
        policy, [_found("CONFIDENTIAL_MARKER", tier=Tier.T1)], DRAFTPILOT, (ATHENA,)
    )
    assert explanation.summary == (
        "The prompt to DraftPilot (a tolerated tool) contained 1 confidentiality marking; "
        "it will be sent, with placeholders, only if you confirm."
    )
    assert explanation.advice == (
        "Confirm to send it with placeholders, or cancel. You can also use Athena Assist instead."
    )


def test_allow_has_no_advice(policy: PolicyDocument) -> None:
    explanation = _explain(policy, [], CHATTERBOX)
    assert explanation.summary == (
        "The prompt to Chatterbox AI (an unapproved tool) contained nothing sensitive; "
        "it was sent unchanged."
    )
    assert explanation.advice is None


def test_counts_of_one_type_from_two_tiers_are_added(policy: PolicyDocument) -> None:
    found = [_found("PERSON", 1, Tier.T0), _found("PERSON", 2, Tier.T1)]
    assert "contained 3 person names;" in _explain(policy, found, CHATTERBOX).summary


def test_custom_data_type_is_named_plainly(policy: PolicyDocument) -> None:
    explanation = _explain(policy, [_found("PROJECT_CODE", 2)], CHATTERBOX, (ATHENA,))
    assert explanation.summary == (
        "The prompt to Chatterbox AI (an unapproved tool) contained 2 project code values; "
        "each value was replaced with a placeholder before sending and restored in the answer."
    )
    assert explanation.advice == (
        "Nothing more is needed: the AI tool saw placeholders only. "
        "To work with the real values, use Athena Assist."
    )


def test_a_rule_on_custom_types_names_the_types_that_were_found() -> None:
    text = (
        "version: 1\nrules:\n"
        "  - name: ours-stay-inside\n"
        "    when: { tool_status: [unapproved], data: [CUSTOM] }\n    action: block\n"
        "  - name: default\n    action: allow\n"
    )
    document = check(text, DataType.BUILT_IN).document
    assert document is not None
    found = [_found("PERSON", 1, Tier.T1), _found("PROJECT_CODE", 2), _found("TICKET")]
    explanation = _explain(document, found, CHATTERBOX)
    assert explanation.summary == (
        "The prompt to Chatterbox AI (an unapproved tool) contained 2 project code values, "
        "1 ticket value and 1 person name; because of the project code values and ticket value, "
        "it was blocked and nothing was sent."
    )
    assert explanation.advice == "Remove the project code values and ticket value and send again."


def test_detector_failure_blocks_with_a_way_forward(policy: PolicyDocument) -> None:
    explanation = _explain(
        policy, [_found("PERSON", tier=Tier.T1)], CHATTERBOX, (ATHENA,), detector_error=True
    )
    assert explanation.rule == "on-error"
    assert explanation.summary == (
        "The checks on the prompt to Chatterbox AI (an unapproved tool) could not finish, "
        "so it was blocked and nothing was sent."
    )
    assert explanation.advice == "Try again in a moment. If it keeps failing, use Athena Assist."


def test_local_fallback_is_stated(policy: PolicyDocument) -> None:
    explanation = _explain(policy, [_found("SECRET")], ATHENA, detector_error=True)
    assert explanation.rule == "secrets-never-leave"
    assert explanation.summary.endswith(
        "The deeper checks could not finish, so this rests on local detection alone."
    )


def test_tainted_tool_call(policy: PolicyDocument) -> None:
    explanation = _explain(
        policy,
        [_found("CLIENT", 3, Tier.T1)],
        channel=Channel.TOOL_CALL,
        tool_name="mail.send_email",
        tainted=True,
        side_effects=True,
        destination=Trust.UNTRUSTED,
    )
    assert explanation.summary == (
        "The agent's call to mail.send_email, able to send or change data and made after the "
        "agent read untrusted content, contained 3 client names; it was blocked."
    )
    assert explanation.advice is not None and "new conversation" in explanation.advice
    assert explanation.alternatives == ()


def test_untrusted_destination_gets_placeholders(policy: PolicyDocument) -> None:
    explanation = _explain(
        policy,
        [_found("CLIENT", 3, Tier.T1)],
        channel=Channel.TOOL_CALL,
        tool_name="mail.send_email",
        side_effects=True,
        destination=Trust.UNTRUSTED,
    )
    assert explanation.summary == (
        "The agent's call to mail.send_email, going to an untrusted destination, contained "
        "3 client names; it went ahead, with every protected value left as a placeholder."
    )


def test_tool_result_is_masked_for_the_model(policy: PolicyDocument) -> None:
    explanation = _explain(
        policy,
        [_found("PERSON", 2, Tier.T1), _found("IBAN")],
        channel=Channel.TOOL_RESULT,
        tool_name="crm.get_client",
        source=Trust.TRUSTED,
    )
    assert explanation.summary == (
        "The result of crm.get_client contained 2 person names and 1 IBAN; the agent's model "
        "received placeholders instead of the real values."
    )
