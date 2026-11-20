import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from seeder.gateway import Gateway
from seeder.main import Settings, run
from seeder.tests.fake_gateway import ADMIN, FakeGateway
from seeder.world import load_world

NOW = datetime(2026, 11, 18, 10, 15, tzinfo=UTC)
ON = Settings(SEED_DEMO_DATA=True, SEEDER_WAIT_SECONDS=30)


def _seed(fake: FakeGateway, settings: Settings = ON, now: datetime = NOW) -> int:
    gateway = Gateway("http://gateway.test", transport=fake.transport(), sleep=lambda _: None)
    try:
        return run(settings, gateway, now)
    finally:
        gateway.close()


@pytest.fixture(scope="module")
def loaded() -> FakeGateway:
    fake = FakeGateway()
    assert _seed(fake) == 0
    return fake


def test_the_directory_carries_every_employee_and_team_range(loaded: FakeGateway) -> None:
    world = load_world()
    assert len(loaded.directory["users"]) == len(world.employees)
    assert {"user_id": "e.papadaki", "display_name": "Eleni Papadaki", "team": "Sales"} in (
        loaded.directory["users"]
    )
    assert {network["team"] for network in loaded.directory["networks"]} == {
        team.name for team in world.teams
    }


def test_the_admin_signs_in_once_and_the_directory_comes_first(loaded: FakeGateway) -> None:
    assert loaded.sign_ins == [ADMIN]
    assert loaded.requests.index("POST /api/directory") < loaded.requests.index(
        "PUT /api/demo/seed-state/directory"
    )


def test_the_protected_data_is_loaded_as_the_seeded_layer(loaded: FakeGateway) -> None:
    assert loaded.term_syncs == 1
    assert len(loaded.documents) == 40
    assert {document["source"] for document in loaded.documents} == {"seeded"}
    assert Counter(document["category"] for document in loaded.documents)["CONTRACT"] == 12
    names = [document["filename"] for document in loaded.documents]
    assert "source-01-ledger_sync.py" in names
    assert loaded.patterns == [
        {"name": "Project code", "regex": r"\bPRJ-[A-Z]{3}-[0-9]{4}\b", "data_type": "PROJECT_CODE"}
    ]


def test_steps_run_in_order_so_logs_and_prompts_find_what_they_need(loaded: FakeGateway) -> None:
    assert loaded.steps[:5] == ["directory", "terms", "corpus", "pattern", "logs"]
    assert loaded.steps[5:] == [f"prompts-{n:02d}" for n in range(1, 11)]
    assert [log["kind"] for log in loaded.logs] == ["squid", "dns"]


def test_about_two_thousand_prompts_arrive_in_batches_of_at_most_two_hundred(
    loaded: FakeGateway,
) -> None:
    assert len(loaded.prompts) == 2000
    assert max(len(batch) for batch in loaded.batches) <= 200
    employees = {employee.user_id for employee in load_world().employees}
    for record in loaded.prompts:
        assert set(record) == {"ts", "user_id", "tool", "text", "enforced"}
        assert record["user_id"] in employees
        assert NOW - timedelta(days=14) <= datetime.fromisoformat(record["ts"]) <= NOW
    assert Counter(record["enforced"] for record in loaded.prompts)[False] > 800


def test_a_second_run_loads_nothing_again(loaded: FakeGateway) -> None:
    before = (len(loaded.documents), len(loaded.logs), len(loaded.batches), loaded.term_syncs)
    writes = len([request for request in loaded.requests if request.startswith(("POST", "PUT"))])
    assert _seed(loaded, now=NOW + timedelta(hours=3)) == 0
    assert (
        len(loaded.documents),
        len(loaded.logs),
        len(loaded.batches),
        loaded.term_syncs,
    ) == before
    after = [request for request in loaded.requests if request.startswith(("POST", "PUT"))]
    assert len(after) == writes + 1  # the sign-in


def test_a_restart_carries_on_from_the_recorded_steps() -> None:
    fake = FakeGateway()
    fake.steps = ["directory", "terms", "corpus", "pattern", "logs", "prompts-01", "prompts-02"]
    assert _seed(fake) == 0
    assert not fake.documents and not fake.logs and not fake.directory
    assert len(fake.batches) == 8


def test_an_existing_pattern_is_not_added_twice() -> None:
    fake = FakeGateway()
    fake.patterns = [{"name": "Project code", "regex": "x", "data_type": "PROJECT_CODE"}]
    assert _seed(fake) == 0
    assert len(fake.patterns) == 1


def test_it_waits_while_the_gateway_is_starting() -> None:
    fake = FakeGateway(unhealthy=3)
    assert _seed(fake) == 0
    assert fake.requests[:4] == ["GET /healthz"] * 4


def test_a_refused_step_ends_with_a_failure_code_and_is_not_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeGateway(broken="/api/protected/terms/sync")
    with caplog.at_level(logging.INFO):
        assert _seed(fake) == 1
    assert fake.steps == ["directory"]
    assert "POST /api/protected/terms/sync answered 500" in caplog.text


def test_with_seeding_switched_off_only_the_directory_is_loaded() -> None:
    fake = FakeGateway()
    assert _seed(fake, Settings(SEED_DEMO_DATA=False)) == 0
    assert fake.steps == ["directory"]
    assert _seed(fake, Settings(SEED_DEMO_DATA=False)) == 0
    assert fake.requests.count("POST /api/directory") == 1


def test_progress_is_logged_without_any_prompt_text(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeGateway()
    with caplog.at_level(logging.DEBUG):
        _seed(fake)
    assert "prompts-10: 200 prompts inspected" in caplog.text
    assert "corpus: 40 documents fingerprinted" in caplog.text
    world = load_world()
    leaked = [client.id for client in world.clients if client.afm in caplog.text]
    assert not leaked
    assert not any(record["text"][:40] in caplog.text for record in fake.prompts[:200])
