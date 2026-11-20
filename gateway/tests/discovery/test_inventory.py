import pytest
from sqlalchemy import select

from gateway.app.core.deps import Deps
from gateway.app.core.types import (
    Action,
    Channel,
    FoundItem,
    PolicyContext,
    Tier,
    ToolRef,
    ToolStatus,
)
from gateway.app.discovery import InventoryService, build
from gateway.app.discovery.catalogue import read_catalogue
from gateway.app.discovery.models import Tool
from gateway.app.discovery.schemas import RiskFactors, ToolUpdate
from gateway.app.policy import PolicyEngine

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

DEMO_TOOLS = {
    "athena-assist": ToolStatus.APPROVED,
    "draftpilot": ToolStatus.TOLERATED,
    "chatterbox-ai": ToolStatus.UNAPPROVED,
}


async def _rows(deps: Deps) -> dict[str, Tool]:
    async with deps.db.session() as session:
        return {row.slug: row for row in (await session.execute(select(Tool))).scalars()}


async def _decide(policy: PolicyEngine, tool: ToolRef, data_type: str) -> tuple[Action, str]:
    ctx = PolicyContext(
        channel=Channel.PROMPT,
        data_types=frozenset({data_type}),
        tool=tool.slug,
        tool_status=tool.status,
    )
    decision = await policy.decide(ctx, [FoundItem(data_type=data_type, count=1, tier=Tier.T2)])
    return decision.action, decision.rule


async def test_catalogue_is_loaded_and_labelled_as_illustrative(
    inventory: InventoryService, deps: Deps
) -> None:
    rows = await _rows(deps)
    catalogue = read_catalogue(deps.settings.defaults_dir)
    assert set(rows) == {entry.slug for entry in catalogue}
    assert 25 <= len(rows) - 4 <= 30
    # No rating of a real product is presented as verified.
    assert {row.rating_source for row in rows.values()} == {"seeded"}
    assert not any(row.needs_review for row in rows.values())
    assert all(1 <= row.risk_score <= 5 for row in rows.values())
    assert {row.status for row in rows.values()} <= {status.value for status in ToolStatus}


async def test_fictional_tools_are_routed_to_mock_upstream(inventory: InventoryService) -> None:
    for slug, status in DEMO_TOOLS.items():
        tool = await inventory.resolve(slug)
        assert tool.status is status
        assert tool.upstream_url == f"http://mock-upstream:9100/tools/{slug}/v1"
        assert (await inventory.resolve(f"app.{slug}.example")).slug == slug
    assistant = await inventory.resolve("company-assistant")
    assert (assistant.status, assistant.category, assistant.upstream_url) == (
        ToolStatus.APPROVED,
        "in-house assistant",
        None,
    )
    real = await inventory.resolve("chatgpt")
    assert real.upstream_url is None


@pytest.mark.parametrize(
    ("tool", "slug"),
    [
        ("claude", "claude"),
        ("claude.ai", "claude"),
        ("https://claude.ai/chat/abc", "claude"),
        ("chat.openai.com:443", "chatgpt"),
        ("eu.api.openai.com", "openai-api"),
        ("gemini.google.com", "gemini"),
    ],
)
async def test_resolve_by_slug_domain_and_subdomain(
    inventory: InventoryService, tool: str, slug: str
) -> None:
    assert (await inventory.resolve(tool)).slug == slug


async def test_unseen_tool_is_unknown_and_not_stored(
    inventory: InventoryService, deps: Deps
) -> None:
    before = len(await _rows(deps))
    by_domain = await inventory.resolve("https://Brand-New.example/chat")
    assert by_domain == ToolRef(
        slug="brand-new.example", name="brand-new.example", status=ToolStatus.UNKNOWN
    )
    # google.com is not Gemini, and a parent domain never matches a listed subdomain.
    assert (await inventory.resolve("google.com")).status is ToolStatus.UNKNOWN
    assert (await inventory.resolve("  ")).slug == "unnamed-tool"
    assert len(await _rows(deps)) == before


async def test_approved_alternatives(inventory: InventoryService) -> None:
    for_chat = await inventory.approved_alternatives("chat assistant")
    assert for_chat[0].slug == "athena-assist"
    assert all(tool.status is ToolStatus.APPROVED for tool in for_chat)
    for_code = await inventory.approved_alternatives("coding assistant")
    assert [tool.slug for tool in for_code] == ["github-copilot", "athena-assist"]


async def test_loading_again_changes_nothing_and_keeps_an_analysts_rating(
    inventory: InventoryService, deps: Deps
) -> None:
    await inventory.update(
        "chatgpt",
        ToolUpdate(status=ToolStatus.APPROVED, risk_score=1, risk_factors=RiskFactors(sso=True)),
    )
    async with deps.db.session() as session:
        row = (await session.execute(select(Tool).where(Tool.slug == "claude"))).scalar_one()
        row.status = "unknown"
    before = await _rows(deps)

    restarted = await build(deps)
    await restarted.aclose()

    after = await _rows(deps)
    assert {slug: row.id for slug, row in after.items()} == {
        slug: row.id for slug, row in before.items()
    }
    chatgpt = after["chatgpt"]
    assert (chatgpt.status, chatgpt.risk_score, chatgpt.rating_source) == (
        "approved",
        1,
        "analyst_confirmed",
    )
    assert chatgpt.risk_factors["sso"] is True
    # A seeded row that nobody rated follows the catalogue again.
    assert after["claude"].status == "tolerated"


async def test_update_confirms_the_rating_and_clears_the_review_flag(
    inventory: InventoryService, deps: Deps
) -> None:
    async with deps.db.session() as session:
        row = (await session.execute(select(Tool).where(Tool.slug == "poe"))).scalar_one()
        row.needs_review = True

    view = await inventory.update("poe", ToolUpdate(status=ToolStatus.TOLERATED, risk_score=2))

    assert view is not None
    assert (view.status, view.risk_score, view.rating_source, view.needs_review) == (
        ToolStatus.TOLERATED,
        2,
        "analyst_confirmed",
        False,
    )
    assert await inventory.update("no-such-tool", ToolUpdate(risk_score=1)) is None


async def test_status_change_alters_the_next_policy_decision(
    inventory: InventoryService, policy: PolicyEngine
) -> None:
    before = await inventory.resolve("chatterbox-ai")
    assert await _decide(policy, before, "CONTRACT") == (Action.BLOCK, "contract-to-unapproved")

    await inventory.update("chatterbox-ai", ToolUpdate(status=ToolStatus.APPROVED))

    after = await inventory.resolve("chatterbox-ai")
    assert after.status is ToolStatus.APPROVED
    assert await _decide(policy, after, "CONTRACT") == (Action.ALLOW, "default")


async def test_blocked_prompt_is_pointed_to_an_approved_tool_that_would_take_it(
    inventory: InventoryService, policy: PolicyEngine
) -> None:
    chatterbox = await inventory.resolve("chatterbox-ai")
    ctx = PolicyContext(
        channel=Channel.PROMPT,
        data_types=frozenset({"CONTRACT"}),
        tool=chatterbox.slug,
        tool_status=chatterbox.status,
    )
    found = [FoundItem(data_type="CONTRACT", count=1, tier=Tier.T2)]
    blocked = await policy.decide(ctx, found)
    assert [tool.slug for tool in blocked.explanation.alternatives] == ["athena-assist"]
    assert blocked.explanation.summary.startswith(
        "The prompt to Unapproved Tool (an unapproved tool)"
    )
    assert blocked.explanation.advice == (
        "Use Approved Tool for this, or remove the contract text and send again."
    )

    # A secret is blocked everywhere, so no tool is suggested.
    secret = ctx.model_copy(update={"data_types": frozenset({"SECRET"})})
    refused = await policy.decide(secret, [FoundItem(data_type="SECRET", count=1, tier=Tier.T0)])
    assert refused.action is Action.BLOCK
    assert refused.explanation.alternatives == ()

    # Once nothing is approved any more, there is nothing to suggest.
    await inventory.update("athena-assist", ToolUpdate(status=ToolStatus.TOLERATED))
    assert (await policy.decide(ctx, found)).explanation.alternatives == ()
