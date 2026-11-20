from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select

from gateway.app.analyst.events import list_events
from gateway.app.core.auth import Admin, CurrentPrincipal
from gateway.app.core.conversation import vault_conversation
from gateway.app.core.services import Svc
from gateway.app.events.models import SNIPPET_CHARS, Event
from gateway.app.privacy.directory import DirectoryImport, DirectorySource
from gateway.app.privacy.schemas import (
    ConversationHoldings,
    IdentityOut,
    MyData,
    Notice,
    PrivacySettings,
    PrivacySettingsUpdate,
)
from gateway.app.privacy.store import RETENTION_DAYS, STORE_SNIPPETS

router = APIRouter(prefix="/api", tags=["privacy"])

SMALL_TEAM_USERS = 3
MY_EVENTS = 100

NOTICE = Notice(
    inspected=[
        "Every prompt you send to an AI tool through this gateway, before it leaves the company",
        "What in-house AI agents read from tools and what they try to send out",
    ],
    kept=[
        "When it happened, your team, the AI tool, and the action taken",
        "Which kinds of data were found and how many of each, never the values",
        f"At most {SNIPPET_CHARS} characters of the masked prompt, with placeholders in place "
        "of every value found",
        "A pseudonym instead of your user ID; an admin can look up who sent one event, "
        "and that lookup is not recorded",
    ],
    never_kept=[
        "The text of your prompts and of the answers you receive",
        "The real values behind placeholders, beyond an encrypted, expiring conversation vault",
        "Passwords, keys and other secrets, which are removed and never stored",
    ],
)


@router.get("/privacy/notice")
async def notice() -> Notice:
    """What employees are told about inspection. Public, so it can be shown before sign-in."""
    return NOTICE


async def _settings(services: Svc) -> PrivacySettings:
    return PrivacySettings(
        retention_days=await services.retention.days(),
        store_snippets=services.events.store_snippets,
        vault_ttl_hours=services.settings.vault_ttl_hours,
        snippet_chars=SNIPPET_CHARS,
        small_team_threshold=SMALL_TEAM_USERS,
    )


@router.get("/privacy/settings")
async def get_settings(_: Admin, services: Svc) -> PrivacySettings:
    return await _settings(services)


@router.put("/privacy/settings")
async def update_settings(body: PrivacySettingsUpdate, _: Admin, services: Svc) -> PrivacySettings:
    await services.store.put(RETENTION_DAYS, body.retention_days)
    await services.store.put(STORE_SNIPPETS, body.store_snippets)
    await services.bus.publish("privacy")
    await services.retention.purge()
    return await _settings(services)


@router.get("/privacy/my-data")
async def my_data(principal: CurrentPrincipal, services: Svc) -> MyData:
    """Everything the system holds about the signed-in user."""
    pseudonym = services.events.pseudonym(principal.user_id)
    mine = Event.user_pseudonym == pseudonym
    page = await list_events(
        services.db, filters=[mine], offset=0, limit=MY_EVENTS, own_team=principal.team
    )
    vault_lifetime = timedelta(hours=services.settings.vault_ttl_hours)
    recent = (
        select(Event.conversation)
        .where(mine, Event.conversation.is_not(None))
        .where(Event.ts >= datetime.now(UTC) - vault_lifetime)
        .distinct()
    )
    async with services.db.session() as session:
        conversations = [row for row in (await session.execute(recent)).scalars() if row]
    holdings = [
        ConversationHoldings(conversation_id=conversation, placeholders=placeholders)
        for conversation in conversations
        if (
            placeholders := await services.vault.describe(
                vault_conversation(principal, conversation, services.keys.pseudonym)
            )
        )
    ]
    return MyData(
        user_id=principal.user_id,
        team=principal.team,
        retention_days=await services.retention.days(),
        event_count=page.total,
        events=page.items,
        conversations=holdings,
    )


@router.get("/events/{event_id}/identity")
async def reveal_identity(event_id: int, _: Admin, services: Svc) -> IdentityOut:
    """The person behind one event. The lookup is not recorded."""
    return await services.identities.reveal(event_id)


@router.post("/directory", status_code=status.HTTP_204_NO_CONTENT)
async def import_directory(
    body: DirectoryImport, _: Admin, services: Svc, source: DirectorySource = "uploaded"
) -> None:
    """Replace the users and address ranges from one source. The directory resolves log lines
    to teams and decides which teams are large enough to be named, so only an admin
    may change it."""
    await services.directory.replace(source, body)
    await services.bus.publish("directory")
