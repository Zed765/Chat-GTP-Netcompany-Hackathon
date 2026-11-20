"""Re-evaluates past events under a draft policy and reports what would change.

Events hold the policy context they were decided on and no raw text, so a replay reads
nothing sensitive. Both policies are evaluated on the same contexts, which isolates the
effect of the draft from that of earlier policy versions.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Row, select

from gateway.app.core.types import Action, PolicyContext
from gateway.app.db.session import Database
from gateway.app.events.models import Event
from gateway.app.policy.document import PolicyDocument
from gateway.app.policy.evaluate import evaluate, with_tool_status
from gateway.app.policy.schemas import ReplayBreakdown, ReplayResult, ReplayTransition

# As in the analyst views: a team this small is reported as "Other".
SMALL_TEAM_USERS = 3
OTHER_TEAMS = "Other"
NO_TOOL = "(no tool)"


@dataclass
class _Group:
    total: int = 0
    changed: int = 0
    users: set[str] = field(default_factory=set)

    def add(self, other: "_Group") -> None:
        self.total += other.total
        self.changed += other.changed
        self.users |= other.users


@dataclass
class _Tally:
    events: int = 0
    transitions: Counter[tuple[Action, Action]] = field(default_factory=Counter)
    teams: dict[str, _Group] = field(default_factory=dict)
    tools: dict[str, _Group] = field(default_factory=dict)

    def count(self, team: str, user: str, tool: str, before: Action, after: Action) -> None:
        changed = before is not after
        self.events += 1
        if changed:
            self.transitions[before, after] += 1
        for group in (self.teams.setdefault(team, _Group()), self.tools.setdefault(tool, _Group())):
            group.total += 1
            group.changed += changed
            group.users.add(user)

    def teams_without_small_ones(self) -> dict[str, _Group]:
        merged: dict[str, _Group] = {}
        for team, group in self.teams.items():
            key = team if len(group.users) >= SMALL_TEAM_USERS else OTHER_TEAMS
            merged.setdefault(key, _Group()).add(group)
        return merged


async def replay(
    db: Database, active: PolicyDocument, draft: PolicyDocument, days: int
) -> ReplayResult:
    since = datetime.now(UTC) - timedelta(days=days)
    statement = select(
        Event.team,
        Event.user_pseudonym,
        Event.tool,
        Event.agent_tool,
        Event.tool_status,
        Event.channel,
        Event.data_types,
        Event.tainted,
        Event.policy_context,
    ).where(Event.ts >= since)
    tally = _Tally()
    async with db.session() as session:
        async for row in await session.stream(statement):
            ctx = with_tool_status(_context(row))
            tally.count(
                row.team,
                row.user_pseudonym,
                row.agent_tool or row.tool or NO_TOOL,
                evaluate(active, ctx).action,
                evaluate(draft, ctx).action,
            )
    return ReplayResult(
        days=days,
        events=tally.events,
        changed=sum(tally.transitions.values()),
        transitions=[
            ReplayTransition(from_action=before, to_action=after, count=count)
            for (before, after), count in tally.transitions.most_common()
        ],
        by_team=_breakdown(tally.teams_without_small_ones()),
        by_tool=_breakdown(tally.tools),
    )


def _context(row: Row[Any]) -> PolicyContext:
    if row.policy_context is not None:
        return PolicyContext.model_validate(row.policy_context)
    # An event recorded without its context still has the main facts in columns.
    return PolicyContext(
        channel=row.channel,
        data_types=frozenset(row.data_types),
        tool=row.agent_tool or row.tool,
        tool_status=row.tool_status,
        team=row.team,
        tainted=row.tainted,
    )


def _breakdown(groups: dict[str, _Group]) -> list[ReplayBreakdown]:
    rows = [
        ReplayBreakdown(key=key, total=group.total, changed=group.changed)
        for key, group in groups.items()
    ]
    return sorted(rows, key=lambda row: (-row.changed, -row.total, row.key))
