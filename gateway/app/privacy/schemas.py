from pydantic import BaseModel, Field

from gateway.app.analyst.schemas import EventOut
from gateway.app.core.types import PlaceholderInfo


class PrivacySettings(BaseModel):
    retention_days: int = Field(ge=1, le=3650)
    store_snippets: bool = Field(
        description="Keep a masked snippet of at most `snippet_chars` characters on events"
    )
    vault_ttl_hours: int
    snippet_chars: int
    small_team_threshold: int


class PrivacySettingsUpdate(BaseModel):
    retention_days: int = Field(ge=1, le=3650)
    store_snippets: bool = True


class IdentityOut(BaseModel):
    event_id: int
    user_id: str
    display_name: str
    team: str


class ConversationHoldings(BaseModel):
    conversation_id: str
    placeholders: list[PlaceholderInfo]


class MyData(BaseModel):
    """Everything the system holds about the signed-in user."""

    user_id: str
    team: str
    retention_days: int
    event_count: int
    events: list[EventOut]
    conversations: list[ConversationHoldings]


class Notice(BaseModel):
    inspected: list[str]
    kept: list[str]
    never_kept: list[str]
