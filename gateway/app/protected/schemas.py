from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from gateway.app.core.types import RowSource, Store, Tier

ImportSource = Literal["uploaded", "seeded"]


class LayerCount(BaseModel):
    source: RowSource
    rows: int
    enabled: int


class GroupOut(BaseModel):
    group: str
    source: RowSource
    data_type: str | None
    rows: int
    enabled: bool


class StoreSummary(BaseModel):
    store: Store
    layers: list[LayerCount]
    groups: list[GroupOut]


class ProtectedSummary(BaseModel):
    pack_version: str
    embedder_id: str
    stale_documents: int
    data_types: list[str] = Field(description="Every type valid in a policy `data` list")
    categories: list[str] = Field(description="The categories a protected document can have")
    stores: list[StoreSummary]


class TermIn(BaseModel):
    term: str = Field(min_length=2, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    data_type: str = "CLIENT"


class TermDraft(BaseModel):
    """One submitted row of a term list, with the fields of `TermIn`. Rows are validated one
    by one: a bad row is reported with its number and the others are imported."""

    model_config = ConfigDict(extra="ignore")

    term: Any = Field(default=None, description="The name to protect, 2 to 200 characters")
    aliases: Any = Field(default=None, description="Other names: a list, or text split on ; or |")
    data_type: Any = Field(default=None, description="Defaults to CLIENT")


class TermOut(TermIn):
    id: UUID
    source: RowSource
    group: str
    enabled: bool
    created: datetime


class TermPage(BaseModel):
    total: int
    items: list[TermOut]


class RowError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    imported: int
    duplicates: int
    errors: list[RowError]


class DocumentOut(BaseModel):
    id: UUID
    label: str
    category: str
    language: str | None
    source: RowSource
    chunks: int
    embedder_id: str
    stale: bool
    enabled: bool
    created: datetime


class DocumentUploadResult(BaseModel):
    document: DocumentOut
    duplicate: bool


class PatternIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    regex: str = Field(min_length=1, max_length=2000)
    data_type: str


class PatternOut(PatternIn):
    id: UUID
    source: RowSource
    group: str
    enabled: bool
    created: datetime


class AssistTurn(BaseModel):
    """A request that added nothing, and what the admin was told about it."""

    request: str = Field(min_length=3, max_length=500)
    message: str = Field(max_length=1000)


class AssistRequest(BaseModel):
    request: str = Field(min_length=3, max_length=500, description="The format, in plain words")
    previous: AssistTurn | None = Field(
        default=None, description="The request this one refines, when the last one added nothing"
    )


class AssistResult(BaseModel):
    added: list[str] = Field(description="The pattern added, by name. Empty when none was")
    message: str = Field(description="One sentence for the admin")


class EnabledBody(BaseModel):
    enabled: bool


class TestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


class TestFinding(BaseModel):
    data_type: str
    start: int
    end: int
    placeholder: str | None
    tier: Tier
    score: float
    recogniser: str
    encoded: bool
    masked: bool
    store: Store | None
    source: RowSource | None
    match_label: str | None


class TestCategory(BaseModel):
    category: str
    tier: Tier
    score: float
    conclusive: bool
    evidence: str
    store: Store | None
    source: RowSource | None
    match_label: str | None


class TestResult(BaseModel):
    masked_text: str
    findings: list[TestFinding]
    categories: list[TestCategory]
    tiers_run: list[Tier]
    timings_ms: dict[str, float]
    notes: list[str]


class RemoveDemoResult(BaseModel):
    terms: int
    documents: int
    patterns: int
