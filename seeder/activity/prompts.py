"""The seeded prompts: about two thousand over fourteen days, shaped so that the dashboard
tells a story. The gateway detects and applies the policy; this module only writes prompts
whose content produces the mix: client data, personal data, contracts, marked texts, secrets.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import Random
from typing import Any

from seeder.activity.profiles import LATE_TEAM, PROFILES, Kind, Tool, allocate, team_tools
from seeder.activity.timeline import Timeline
from seeder.compose.prompts import PromptFactory, load_prompts
from seeder.compose.slots import Language
from seeder.world import World

BATCH_SIZE = 200
FIRST_WEEK_SHARE = 0.45
SENSITIVE_GROUPS = {"el": 0.55, "en": 0.30, "greeklish": 0.08, "mixed": 0.07}
REQUESTS: dict[Language, str] = {
    "el": "Συνόψισε τους παρακάτω όρους της σύμβασης σε τρία σημεία.",
    "en": "Summarise these contract clauses in three bullet points.",
}


@dataclass(frozen=True)
class SeedPrompt:
    ts: datetime
    user_id: str
    team: str
    tool: Tool
    kind: Kind
    text: str
    enforced: bool

    def record(self) -> dict[str, Any]:
        """The `PromptRecord` the gateway's ingestion endpoint takes."""
        return {
            "ts": self.ts.isoformat(),
            "user_id": self.user_id,
            "tool": self.tool.slug,
            "text": self.text,
            "enforced": self.enforced,
        }


def contract_excerpts(corpus_dir: Path) -> dict[Language, list[str]]:
    """Two consecutive clauses from each contract in the corpus, by language."""
    excerpts: dict[Language, list[str]] = {"el": [], "en": []}
    manifest = (corpus_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    for row in map(json.loads, manifest):
        if row["kind"] != "contract":
            continue
        text = (corpus_dir / row["file"]).read_text(encoding="utf-8")
        clauses = [block for block in text.split("\n\n") if block[:1].isdigit()]
        excerpts[row["language"]] += [
            "\n\n".join(clauses[index : index + 2]) for index in range(0, len(clauses) - 1, 2)
        ]
    return excerpts


class _Writer:
    """Writes the text of one prompt of a given kind."""

    def __init__(self, world: World, corpus_dir: Path) -> None:
        self._world = world
        self._factory = PromptFactory(world)
        self._library = load_prompts()
        self._excerpts = contract_excerpts(corpus_dir)

    def write(self, kind: Kind, team: str, rng: Random) -> str:
        language: Language = "el" if rng.random() < 0.6 else "en"
        if kind == "contract":
            return f"{REQUESTS[language]}\n\n{rng.choice(self._excerpts[language])}"
        if kind in ("client", "personal"):
            group = rng.choices(list(SENSITIVE_GROUPS), weights=list(SENSITIVE_GROUPS.values()))[0]
            template = rng.choice(self._library.sensitive[group])
            if kind == "personal":
                return self._factory.about_outsider(template, group, rng).text
            client = self._factory.client_for(rng, template, team)
            return self._factory.about_client(template, group, rng, client).text
        templates = {
            "benign": self._library.benign[language]
            + self._library.hard_negatives["code_no_secret"][language],
            "marked": self._library.marked[language],
            "secret": self._library.secrets[language],
        }[kind]
        return self._factory.about_outsider(rng.choice(templates), language, rng).text


def plan_prompts(
    world: World, inventory: Sequence[Tool], timeline: Timeline, corpus_dir: Path
) -> list[SeedPrompt]:
    rng = Random(f"{world.seed}:prompts")
    writer = _Writer(world, corpus_dir)
    prompts = []
    for team, profile in PROFILES.items():
        staff = [employee for employee in world.employees if employee.team == team]
        weights = [1 / (rank + 1) ** 0.5 for rank in range(len(staff))]
        enforced_from = timeline.late_enforced_from if team == LATE_TEAM else timeline.enforced_from
        first_week = round(profile.prompts * FIRST_WEEK_SHARE)
        periods = (
            (first_week, timeline.start, timeline.enforced_from),
            (profile.prompts - first_week, timeline.enforced_from, timeline.now),
        )
        for count, start, end in periods:
            kinds = allocate(count, profile.kinds)
            tools = allocate(count, team_tools(team, inventory))
            rng.shuffle(kinds)
            rng.shuffle(tools)
            moments = timeline.sample(rng, count, start, end)
            for ts, kind, tool in zip(moments, kinds, tools, strict=True):
                prompts.append(
                    SeedPrompt(
                        ts=ts,
                        user_id=rng.choices(staff, weights=weights)[0].user_id,
                        team=team,
                        tool=tool,
                        kind=kind,
                        text=writer.write(kind, team, rng),
                        enforced=ts >= enforced_from,
                    )
                )
    return sorted(prompts, key=lambda prompt: prompt.ts)


def batches(prompts: Sequence[SeedPrompt]) -> list[list[SeedPrompt]]:
    return [
        list(prompts[start : start + BATCH_SIZE]) for start in range(0, len(prompts), BATCH_SIZE)
    ]
