"""What the event writer stores, and what a failure of it may say."""

import logging
import traceback
from typing import Any

import pytest
from sqlalchemy import text

from gateway.app.core.keys import Keys
from gateway.app.core.types import Action, Channel, InjectionVerdict, PolicyContext
from gateway.app.db.session import Database
from gateway.app.events.writer import EventRecord, EventWriteError, EventWriter

USER = "v.tsioutsias"
SNIPPET = "Reply to <PERSON_1> about tax number <AFM_1>"
CONVERSATION = "conversation-of-eleni"
pytestmark = pytest.mark.integration


def _record(**changes: Any) -> EventRecord:
    fields: dict[str, Any] = {
        "user_id": USER,
        "team": "Sales",
        "channel": Channel.PROMPT,
        "action": Action.REDACT,
        "rule": "pii-and-client-data",
        "policy_version": 1,
        "data_counts": {"AFM": 1},
        "masked_snippet": SNIPPET,
        "conversation_id": CONVERSATION,
    }
    return EventRecord(**{**fields, **changes})


async def test_nul_characters_are_dropped_and_the_event_is_stored(db: Database, keys: Keys) -> None:
    writer = EventWriter(db, keys.pseudonym)
    record = _record(
        tool="chatter\x00box-ai",
        rule="pii-and-\x00client-data",
        data_counts={"AFM\x00": 1},
        masked_snippet="Reply to <PERSON_1>\x00 about tax number <AFM_1>",
        trace_id="trace\x00",
        agent_tool="mail.send\x00_email",
        injection=InjectionVerdict(flagged=True, confidence=0.9, technique="role\x00play"),
        policy_context=PolicyContext(
            channel=Channel.PROMPT, data_types=frozenset({"AFM\x00"}), tool="chatter\x00box-ai"
        ),
        error="The classifier\x00 did not answer",
    )

    event_id = await writer.write(record)

    async with db.session() as session:
        stored = (
            await session.execute(text("SELECT * FROM events WHERE id = :id"), {"id": event_id})
        ).one()
    assert stored.masked_snippet == SNIPPET
    assert (stored.tool, stored.rule) == ("chatterbox-ai", "pii-and-client-data")
    assert (stored.data_types, stored.data_counts) == (["AFM"], {"AFM": 1})
    assert (stored.trace_id, stored.agent_tool) == ("trace", "mail.send_email")
    assert stored.injection["technique"] == "roleplay"
    assert stored.policy_context["tool"] == "chatterbox-ai"
    assert stored.policy_context["data_types"] == ["AFM"]
    assert stored.error == "The classifier did not answer"


async def test_a_failed_write_says_what_kind_of_failure_it_was_and_nothing_else(
    db: Database, keys: Keys, caplog: pytest.LogCaptureFixture
) -> None:
    writer = EventWriter(db, keys.pseudonym)
    too_large_for_the_column = 2**40

    with caplog.at_level(logging.DEBUG), pytest.raises(EventWriteError) as failure:
        await writer.write(_record(policy_version=too_large_for_the_column))

    shown = "".join(traceback.format_exception(failure.value)) + caplog.text
    for parameter in (SNIPPET, CONVERSATION, writer.pseudonym(USER), str(too_large_for_the_column)):
        assert parameter not in shown


async def test_statement_logging_never_shows_a_parameter(
    database_url: str, keys: Keys, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")
    database = Database(database_url)
    writer = EventWriter(database, keys.pseudonym)
    try:
        await writer.write(_record())
    finally:
        await database.dispose()

    assert "INSERT INTO events" in caplog.text
    for parameter in (SNIPPET, CONVERSATION, writer.pseudonym(USER)):
        assert parameter not in caplog.text
