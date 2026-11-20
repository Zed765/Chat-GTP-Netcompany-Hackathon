import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random

import pytest

from scripts.sample_log import UNKNOWN_AI_DOMAIN
from seeder.activity.logs import (
    ORDINARY_HOSTS,
    UNKNOWN_AI_HOSTS,
    dns_log,
    plan_visits,
    registrable_domain,
    squid_log,
)
from seeder.activity.profiles import LATE_TEAM, PROFILES, allocate
from seeder.activity.prompts import SeedPrompt, plan_prompts
from seeder.activity.timeline import Timeline
from seeder.tests.fake_gateway import INVENTORY
from seeder.world import DATA_DIR, load_world

DESCRIPTIONS = Path(__file__).resolve().parents[1] / "site_descriptions.json"
# A Monday morning, a Wednesday and a Sunday night: the story must hold whenever it is seeded.
MOMENTS = [
    datetime(2026, 11, 16, 7, 5, tzinfo=UTC),
    datetime(2026, 11, 18, 14, 0, tzinfo=UTC),
    datetime(2026, 11, 22, 23, 30, tzinfo=UTC),
]


def _plan(now: datetime) -> list[SeedPrompt]:
    return plan_prompts(load_world(), INVENTORY, Timeline(now), DATA_DIR / "corpus")


def test_allocation_is_exact() -> None:
    kinds = allocate(101, {"a": 0.5, "b": 0.3, "c": 0.2})
    assert len(kinds) == 101
    assert Counter(kinds) == {"a": 51, "b": 30, "c": 20}


def test_the_plan_is_the_same_for_the_same_moment() -> None:
    assert _plan(MOMENTS[1]) == _plan(MOMENTS[1])


@pytest.mark.parametrize("now", MOMENTS)
def test_the_last_seven_days_answer_the_briefs_question(now: datetime) -> None:
    """Client data to unapproved tools: three teams or more, two tools or more, clear ranks."""
    prompts = _plan(now)
    assert len(prompts) == sum(profile.prompts for profile in PROFILES.values()) == 2000
    assert all(timedelta(0) <= now - prompt.ts <= timedelta(days=14) for prompt in prompts)
    week = [
        prompt
        for prompt in prompts
        if prompt.ts >= now - timedelta(days=7)
        and prompt.kind == "client"
        and prompt.tool.status == "unapproved"
    ]
    by_team = Counter(prompt.team for prompt in week)
    assert len(by_team) >= 3
    assert len({prompt.tool.slug for prompt in week}) >= 2
    sales, support, finance = by_team["Sales"], by_team[LATE_TEAM], by_team["Finance"]
    assert sales >= support + 10 and support >= finance + 10 and finance >= 5


@pytest.mark.parametrize("now", MOMENTS)
def test_the_first_week_is_observed_and_the_second_enforced(now: datetime) -> None:
    prompts = _plan(now)
    cutoff = now - timedelta(days=7)
    assert not any(prompt.enforced for prompt in prompts if prompt.ts < cutoff)
    on_time = [p for p in prompts if p.ts >= cutoff and p.team != LATE_TEAM]
    assert on_time and all(prompt.enforced for prompt in on_time)
    late = Counter(p.enforced for p in prompts if p.ts >= cutoff and p.team == LATE_TEAM)
    assert late[False] >= 20 and late[True] >= 20


def test_prompts_cover_every_kind_and_both_languages() -> None:
    prompts = _plan(MOMENTS[1])
    kinds = Counter(prompt.kind for prompt in prompts)
    assert set(kinds) == {"benign", "client", "personal", "contract", "marked", "secret"}
    assert 0.45 <= kinds["benign"] / len(prompts) <= 0.6
    greek = sum(bool(re.search("[α-ω]", prompt.text)) for prompt in prompts)
    assert 0.4 <= greek / len(prompts) <= 0.8
    scene_client = load_world().scene_client
    assert any(scene_client.trade_name in prompt.text for prompt in prompts)


def test_logs_follow_the_documented_formats() -> None:
    world = load_world()
    timeline = Timeline(MOMENTS[1])
    visits = plan_visits(world, INVENTORY, timeline, Random(5))
    assert 6000 <= len(visits) <= 12000
    assert all(timeline.start <= visit.at <= timeline.now for visit in visits)
    squid = re.compile(
        r"\d{10}\.\d{3} +\d+ 10\.20\.\d\.\d+ TCP_TUNNEL/200 \d+ CONNECT [\w.-]+:443 "
        r"[a-z]\.[a-z]+ HIER_DIRECT/203\.0\.113\.\d+ -"
    )
    dns = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ 10\.20\.\d\.\d+ [\w.-]+ A")
    assert all(squid.fullmatch(line) for line in squid_log(visits, Random(5)).splitlines())
    assert all(dns.fullmatch(line) for line in dns_log(visits).splitlines())
    users = {line.split()[7] for line in squid_log(visits, Random(5)).splitlines()}
    assert users == {employee.user_id for employee in world.employees}


def test_logs_reach_catalogue_tools_the_fictional_ones_unknown_ai_and_ordinary_sites() -> None:
    visits = plan_visits(load_world(), INVENTORY, Timeline(MOMENTS[1]), Random(5))
    hosts = Counter(visit.host for visit in visits)
    known = {domain for tool in INVENTORY for domain in tool.domains}
    for demo in ("athena-assist.example", "draftpilot.example", "chatterbox-ai.example"):
        assert hosts[demo] > 50
    assert len(known & set(hosts)) >= 10
    assert set(UNKNOWN_AI_HOSTS) <= set(hosts)
    assert set(ORDINARY_HOSTS) <= set(hosts)


def test_every_host_outside_the_inventory_has_a_description() -> None:
    descriptions = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
    outside = {registrable_domain(host) for host in (*UNKNOWN_AI_HOSTS, *ORDINARY_HOSTS)}
    # One more described AI service is kept out of the seeded logs: `make sample-log`
    # brings it in, to show discovery finding something new.
    assert set(descriptions) == outside | {UNKNOWN_AI_DOMAIN}
    for entry in descriptions.values():
        assert set(entry) == {"title", "description"}
    for host in UNKNOWN_AI_HOSTS:
        assert "AI" in descriptions[registrable_domain(host)]["description"]
    assert len(UNKNOWN_AI_HOSTS) >= 5
