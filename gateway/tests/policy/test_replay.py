from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from gateway.app.core.deps import Deps
from gateway.app.core.types import Action, Channel, DataType, PolicyContext, ToolStatus
from gateway.app.events.writer import EventRecord, EventWriter
from gateway.app.policy import PolicyEngine
from gateway.app.policy.document import PolicyDocument, check
from gateway.app.policy.replay import OTHER_TEAMS, replay
from gateway.app.policy.schemas import ReplayBreakdown, ReplayTransition

# The fixtures open database connections on the session loop, so the tests run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

DEFAULT_POLICY = (Path(__file__).resolve().parents[3] / "policies" / "default.yaml").read_text(
    encoding="utf-8"
)


class Seeded:
    """Events for one made-up team, tool and small team, so other tests' events cannot match."""

    def __init__(self, deps: Deps) -> None:
        tag = uuid4().hex[:8]
        self.team = f"Replay-{tag}"
        self.small_team = f"Tiny-{tag}"
        self.tool = f"replay-tool-{tag}"
        self._writer = EventWriter(deps.db, deps.keys.pseudonym)

    def draft(self) -> PolicyDocument:
        """The default policy, plus a block on source code for the two made-up teams."""
        rule = (
            f"  - name: no-code-for-replay-teams\n"
            f"    when: {{ team: [{self.team}, {self.small_team}], data: [SOURCE_CODE] }}\n"
            f"    action: block\n\n"
        )
        document = check(DEFAULT_POLICY.replace("rules:\n", f"rules:\n{rule}"), DataType.BUILT_IN)
        assert document.document is not None and document.valid, document.issues
        return document.document

    async def event(
        self,
        user: str,
        data: str,
        *,
        team: str | None = None,
        days_ago: float = 1,
        action: Action = Action.WARN,
        with_context: bool = True,
    ) -> None:
        team = team or self.team
        context = PolicyContext(
            channel=Channel.PROMPT,
            data_types=frozenset({data}),
            tool=self.tool,
            tool_status=ToolStatus.UNAPPROVED,
            team=team,
        )
        await self._writer.write(
            EventRecord(
                user_id=user,
                team=team,
                channel=Channel.PROMPT,
                action=action,
                rule="source-code-warning" if action is Action.WARN else "pii-and-client-data",
                policy_version=1,
                tool=self.tool,
                tool_status=ToolStatus.UNAPPROVED,
                data_counts={data: 1},
                policy_context=context if with_context else None,
                ts=datetime.now(UTC) - timedelta(days=days_ago),
            )
        )


@pytest.fixture
async def seeded(deps: Deps) -> Seeded:
    seeded = Seeded(deps)
    for user in ("u1", "u2", "u3", "u1"):
        await seeded.event(user, "SOURCE_CODE")
    for user in ("u1", "u2"):
        await seeded.event(user, "PERSON", action=Action.REDACT)
    await seeded.event("u3", "SOURCE_CODE", with_context=False)
    await seeded.event("u2", "SOURCE_CODE", days_ago=10)
    await seeded.event("solo", "SOURCE_CODE", team=seeded.small_team)
    return seeded


def _row(rows: list[ReplayBreakdown], key: str) -> ReplayBreakdown | None:
    return next((row for row in rows if row.key == key), None)


async def test_replay_shows_what_a_draft_changes(
    engine: PolicyEngine, deps: Deps, seeded: Seeded
) -> None:
    result = await replay(deps.db, engine.document, seeded.draft(), days=7)

    assert result.days == 7
    assert result.events >= 8
    assert result.changed == 6
    assert result.transitions == [
        ReplayTransition(from_action=Action.WARN, to_action=Action.BLOCK, count=6)
    ]
    # Five warnings for the team, one of them recorded without its context, become blocks.
    assert _row(result.by_team, seeded.team) == ReplayBreakdown(key=seeded.team, total=7, changed=5)
    assert _row(result.by_tool, seeded.tool) == ReplayBreakdown(key=seeded.tool, total=8, changed=6)
    assert result.by_team[0].changed >= result.by_team[-1].changed


async def test_a_team_of_fewer_than_three_people_is_reported_as_other(
    engine: PolicyEngine, deps: Deps, seeded: Seeded
) -> None:
    result = await replay(deps.db, engine.document, seeded.draft(), days=7)
    assert _row(result.by_team, seeded.small_team) is None
    other = _row(result.by_team, OTHER_TEAMS)
    assert other is not None and other.changed >= 1


async def test_window_is_the_last_n_days(engine: PolicyEngine, deps: Deps, seeded: Seeded) -> None:
    result = await replay(deps.db, engine.document, seeded.draft(), days=14)
    assert _row(result.by_team, seeded.team) == ReplayBreakdown(key=seeded.team, total=8, changed=6)


async def test_the_active_policy_replayed_against_itself_changes_nothing(
    engine: PolicyEngine, deps: Deps, seeded: Seeded
) -> None:
    result = await replay(deps.db, engine.document, engine.document, days=30)
    assert result.events >= 9
    assert (result.changed, result.transitions) == (0, [])
    assert all(row.changed == 0 for row in result.by_team + result.by_tool)


async def test_replay_counts_a_stored_custom_type_under_custom(deps: Deps) -> None:
    seeded = Seeded(deps)
    await seeded.event("u1", "PROJECT_CODE", action=Action.ALLOW)
    await seeded.event("u2", "PROJECT_CODE", action=Action.ALLOW, with_context=False)
    await seeded.event("u3", "ORG", action=Action.ALLOW)
    without_custom = check(DEFAULT_POLICY.replace(", CUSTOM]", "]"), DataType.BUILT_IN).document
    with_custom = check(DEFAULT_POLICY, DataType.BUILT_IN).document
    assert without_custom is not None and with_custom is not None
    assert without_custom != with_custom

    result = await replay(deps.db, without_custom, with_custom, days=7)
    assert _row(result.by_tool, seeded.tool) == ReplayBreakdown(key=seeded.tool, total=3, changed=2)
    assert ReplayTransition(from_action=Action.ALLOW, to_action=Action.REDACT, count=2) in (
        result.transitions
    )


async def test_events_hold_nothing_a_replay_could_leak(deps: Deps, seeded: Seeded) -> None:
    async with deps.db.session() as session:
        rows = await session.execute(
            text("SELECT row_to_json(e)::text FROM events e WHERE tool = :tool"),
            {"tool": seeded.tool},
        )
        stored = "\n".join(row[0] for row in rows)
    assert stored and "u1" not in stored and "solo" not in stored
