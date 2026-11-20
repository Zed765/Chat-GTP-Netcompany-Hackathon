from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.deps import Deps
from gateway.app.core.types import (
    Action,
    Channel,
    DataType,
    FoundItem,
    InjectionProtection,
    PolicyContext,
    RowSource,
    Tier,
    ToolStatus,
)
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.patterns import PatternRule
from gateway.app.discovery import InventoryService
from gateway.app.policy import PolicyEngine, build
from gateway.app.policy.document import PolicyInvalidError
from gateway.app.policy.models import PolicyVersion

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

ADMIN = DEMO_USERS[1]
DEFAULT_POLICY = (Path(__file__).resolve().parents[3] / "policies" / "default.yaml").read_text(
    encoding="utf-8"
)
# The default policy with its last warning turned into a block.
STRICTER = DEFAULT_POLICY.replace(
    "data: [SOURCE_CODE]\n    action: warn", "data: [SOURCE_CODE]\n    action: block"
)
SOURCE_CODE_TO_TOLERATED = PolicyContext(
    channel=Channel.PROMPT,
    data_types=frozenset({"SOURCE_CODE"}),
    tool="draftpilot",
    tool_status=ToolStatus.TOLERATED,
)
FOUND = [FoundItem(data_type="SOURCE_CODE", count=1, tier=Tier.T2)]


async def _versions(deps: Deps) -> list[PolicyVersion]:
    async with deps.db.session() as session:
        rows = await session.execute(select(PolicyVersion).order_by(PolicyVersion.version))
        return list(rows.scalars())


async def test_first_start_saves_the_default_policy_as_version_one(
    engine: PolicyEngine, deps: Deps
) -> None:
    assert STRICTER != DEFAULT_POLICY
    assert engine.version == 1
    assert engine.injection_protection is InjectionProtection.STANDARD
    [first] = await _versions(deps)
    assert (first.version, first.active, first.author) == (1, True, "system")
    assert first.yaml == DEFAULT_POLICY

    restarted = await build(deps, InventoryService(deps))
    assert restarted.version == 1
    assert len(await _versions(deps)) == 1


async def test_activation_saves_and_reloads_every_engine(engine: PolicyEngine, deps: Deps) -> None:
    other_worker = await build(deps, InventoryService(deps))
    before = await engine.decide(SOURCE_CODE_TO_TOLERATED, FOUND)
    assert (before.action, before.rule, before.policy_version) == (
        Action.WARN,
        "source-code-warning",
        1,
    )

    saved = await engine.activate(STRICTER, ADMIN, "Block source code")

    assert (saved.version, saved.active, saved.note) == (2, True, "Block source code")
    assert saved.author == ADMIN.display_name and saved.created is not None
    for running in (engine, other_worker):
        after = await running.decide(SOURCE_CODE_TO_TOLERATED, FOUND)
        assert (after.action, after.policy_version) == (Action.BLOCK, 2)
    assert [(row.version, row.active) for row in await _versions(deps)] == [(1, False), (2, True)]


async def test_invalid_policy_is_refused_and_nothing_changes(
    engine: PolicyEngine, deps: Deps
) -> None:
    broken = DEFAULT_POLICY.replace("data: [SECRET]", "data: [SECRETS]")
    with pytest.raises(PolicyInvalidError) as refused:
        await engine.activate(broken, ADMIN)
    [issue] = refused.value.issues
    assert issue.path == "rules[0].when.data[0]"
    assert "did you mean `SECRET`" in issue.message
    assert engine.version == 1
    assert len(await _versions(deps)) == 1


async def test_injection_protection_is_a_policy_version(engine: PolicyEngine, deps: Deps) -> None:
    saved = await engine.set_injection_protection(InjectionProtection.OFF, ADMIN)

    assert saved.version == 2 and saved.note == "Injection protection set to off"
    assert engine.injection_protection is InjectionProtection.OFF
    changed = [
        (old, new)
        for old, new in zip(DEFAULT_POLICY.splitlines(), saved.yaml.splitlines(), strict=True)
        if old != new
    ]
    assert changed == [("injection_protection: standard", "injection_protection: off")]

    same = await engine.set_injection_protection(InjectionProtection.OFF, ADMIN)
    assert same.version == 2
    assert len(await _versions(deps)) == 2


async def test_only_one_version_is_ever_active(engine: PolicyEngine, deps: Deps) -> None:
    for level in (InjectionProtection.DETAILED, InjectionProtection.OFF):
        await engine.set_injection_protection(level, ADMIN)
    await engine.activate(STRICTER, ADMIN)
    async with deps.db.session() as session:
        active = select(func.count()).select_from(PolicyVersion).where(PolicyVersion.active)
        assert (await session.execute(active)).scalar_one() == 1
    assert engine.version == 4


async def test_custom_data_types_come_from_the_hook(engine: PolicyEngine) -> None:
    with_projects = DEFAULT_POLICY.replace(
        "rules:\n",
        "rules:\n  - name: project-codes\n    when: { data: [PROJECT] }\n    action: block\n\n",
    )
    unknown = await engine.check(with_projects)
    assert [issue.path for issue in unknown.issues] == ["rules[0].when.data[0]"]

    engine.known_data_types = lambda: DataType.BUILT_IN | {"PROJECT"}
    assert (await engine.check(with_projects)).valid
    await engine.activate(with_projects, ADMIN)
    ctx = PolicyContext(
        channel=Channel.PROMPT, data_types=frozenset({"PROJECT"}), tool_status=ToolStatus.APPROVED
    )
    decision = await engine.decide(ctx, [FoundItem(data_type="PROJECT", count=2, tier=Tier.T0)])
    assert (decision.action, decision.rule, decision.matched_types) == (
        Action.BLOCK,
        "project-codes",
        ("PROJECT",),
    )
    assert "2 project values" in decision.explanation.summary

    # The type disappears again: the saved policy still loads, and its rule stops matching.
    engine.known_data_types = lambda: DataType.BUILT_IN
    await engine.reload()
    assert engine.version == 2


async def test_a_company_pattern_is_masked_for_an_unapproved_tool_without_a_policy_edit(
    engine: PolicyEngine,
) -> None:
    """The demo organisation's project codes, found by its own pattern, under the default policy."""
    pattern = PatternRule(
        "project-code",
        "Project code",
        r"\bPRJ-[A-Z]{3}-[0-9]{4}\b",
        "PROJECT_CODE",
        RowSource.SEEDED,
        "custom",
    )
    detector = LocalEngine([pattern], [], None)
    for text, action, rule in (
        (
            "What is the budget status of PRJ-ABC-1234 and PRJ-XYZ-9876?",
            Action.REDACT,
            "pii-and-client-data",
        ),
        ("What is a good outline for a budget status report?", Action.ALLOW, "default"),
    ):
        counts = Counter(finding.data_type for finding in detector.detect(text).findings)
        ctx = PolicyContext(
            channel=Channel.PROMPT,
            data_types=frozenset(counts),
            tool="chatterbox-ai",
            tool_status=ToolStatus.UNAPPROVED,
        )
        found = [FoundItem(data_type=kind, count=n, tier=Tier.T0) for kind, n in counts.items()]
        decision = await engine.decide(ctx, found)
        assert (decision.action, decision.rule) == (action, rule), text
        assert decision.matched_types == tuple(counts)


async def test_prompt_without_a_tool_status_is_never_treated_as_trusted(
    engine: PolicyEngine,
) -> None:
    found = [FoundItem(data_type="IBAN", count=1, tier=Tier.T0)]
    for tool in (None, "never-seen.example"):
        ctx = PolicyContext(channel=Channel.PROMPT, data_types=frozenset({"IBAN"}), tool=tool)
        decision = await engine.decide(ctx, found)
        assert (decision.action, decision.rule) == (Action.REDACT, "pii-and-client-data")


async def test_activating_the_active_text_again_saves_nothing(
    engine: PolicyEngine, deps: Deps
) -> None:
    same = await engine.activate(DEFAULT_POLICY, ADMIN, "Nothing changed")
    assert (same.version, same.author) == (1, "system")
    assert len(await _versions(deps)) == 1
