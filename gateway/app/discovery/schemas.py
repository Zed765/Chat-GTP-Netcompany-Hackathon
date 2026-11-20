from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from gateway.app.core.types import ToolStatus

RatingSource = Literal["seeded", "model_drafted", "analyst_confirmed"]
LogKind = Literal["squid", "dns"]


class RiskFactors(BaseModel):
    """Illustrative unless `rating_source` is `analyst_confirmed`. `None` means unknown."""

    trains_on_customer_data: bool | None = None
    retention_days: int | None = None
    data_residency: str | None = None
    enterprise_terms: bool | None = None
    sso: bool | None = None
    certifications: list[str] = Field(default_factory=list)


class TeamUsage(BaseModel):
    team: str
    requests: int


class ToolOut(BaseModel):
    slug: str
    name: str
    domains: list[str]
    category: str
    description: str | None
    status: ToolStatus
    risk_score: int = Field(ge=1, le=5)
    risk_factors: RiskFactors
    rating_source: RatingSource
    needs_review: bool
    review_note: str | None = Field(
        default=None, description="Why discovery flagged this tool as an AI service"
    )
    is_demo: bool = Field(description="A fictional tool served by mock-upstream; usable in Chat")
    first_seen: datetime | None
    last_seen: datetime | None
    requests_14d: int
    usage_by_team: list[TeamUsage]


class ToolUpdate(BaseModel):
    """Any change marks the rating as confirmed by an analyst and clears the review flag."""

    status: ToolStatus | None = None
    risk_score: int | None = Field(default=None, ge=1, le=5)
    risk_factors: RiskFactors | None = None


class IngestionOut(BaseModel):
    id: int
    created: datetime
    filename: str
    kind: LogKind
    lines: int = Field(description="Log lines read, not counting blank lines and comments")
    malformed: int = Field(description="Lines that could not be parsed and were skipped")
    matched: int = Field(description="Lines that went to a tool in the inventory")
    new_tools: int


class IngestionResult(IngestionOut):
    duplicate: bool
    new_tool_slugs: list[str]
