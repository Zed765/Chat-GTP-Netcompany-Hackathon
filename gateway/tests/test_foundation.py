import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from gateway.app.config import MISSING_KEY, MissingKeyError, Settings, get_settings
from gateway.app.core.auth import DEMO_USERS, issue_token, read_token
from gateway.app.core.keys import Keys
from gateway.app.core.types import Action, Channel
from gateway.app.db.session import Database
from gateway.app.events.writer import EventRecord, EventWriter
from gateway.app.main import create_app
from gateway.app.migrate import ALEMBIC_INI


def test_openapi_builds() -> None:
    spec = create_app().openapi()
    assert "/v1/chat/completions" in spec["paths"]
    assert {"Trace", "TraceSummary"} <= set(spec["components"]["schemas"])


@pytest.mark.parametrize("key", [None, "", "  "])
def test_a_key_is_required(key: str | None) -> None:
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY is required"):
        Settings(OPENAI_API_KEY=key)
    assert Settings(OPENAI_API_KEY="k").api_key == "k"


def test_a_missing_key_ends_start_up_with_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as stopped:
            get_settings()
    finally:
        get_settings.cache_clear()
    assert stopped.value.code == MISSING_KEY


def test_session_token_round_trip(keys: Keys) -> None:
    user = DEMO_USERS[0]
    assert read_token(issue_token(user, keys.session, hours=1), keys.session) == user


@pytest.mark.integration
def test_the_migrations_build_the_tables_the_models_describe(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    command.check(config)


@pytest.mark.integration
async def test_event_is_pseudonymous_and_visible_in_view(db: Database, keys: Keys) -> None:
    writer = EventWriter(db, keys.pseudonym)
    event_id = await writer.write(
        EventRecord(
            user_id="v.tsioutsias",
            team="Sales",
            channel=Channel.PROMPT,
            action=Action.REDACT,
            rule="pii-and-client-data",
            policy_version=1,
            data_counts={"AFM": 1, "PERSON": 2},
        )
    )
    async with db.session() as session:
        stored = (
            await session.execute(
                text("SELECT user_pseudonym, data_types FROM events WHERE id = :id"),
                {"id": event_id},
            )
        ).one()
        view_columns = (await session.execute(text("SELECT * FROM v_events LIMIT 1"))).keys()
    assert stored.user_pseudonym == writer.pseudonym("v.tsioutsias") != "v.tsioutsias"
    assert stored.data_types == ["AFM", "PERSON"]
    assert "user_pseudonym" not in view_columns
