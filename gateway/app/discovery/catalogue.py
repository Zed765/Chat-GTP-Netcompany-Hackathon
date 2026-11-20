"""Loads `defaults/tools.yaml`, the catalogue of well-known AI tools, into the inventory."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.types import ToolStatus
from gateway.app.discovery.models import Tool
from gateway.app.discovery.schemas import RiskFactors

CATALOGUE_FILE = "tools.yaml"
SEEDED = "seeded"
_CATALOGUE_LOCK = 741_003


class CatalogueTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=120)
    name: str = Field(min_length=1, max_length=200)
    domains: list[str] = Field(default_factory=list)
    category: str = Field(min_length=1, max_length=60)
    status: ToolStatus
    risk_score: int = Field(ge=1, le=5)
    risk_factors: RiskFactors = RiskFactors()
    description: str
    hosted_by_mock_upstream: bool = False


class Catalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[CatalogueTool]


def read_catalogue(defaults_dir: Path) -> list[CatalogueTool]:
    content = (defaults_dir / CATALOGUE_FILE).read_text(encoding="utf-8")
    return Catalogue.model_validate(yaml.safe_load(content)).tools


async def sync_catalogue(
    session: AsyncSession, entries: list[CatalogueTool], mock_upstream_url: str
) -> None:
    """Add new catalogue tools and refresh the rest, leaving an analyst's rating alone."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CATALOGUE_LOCK})
    slugs = [entry.slug for entry in entries]
    rows = (await session.execute(select(Tool).where(Tool.slug.in_(slugs)))).scalars()
    existing = {row.slug: row for row in rows}
    for entry in entries:
        row = existing.get(entry.slug)
        if row is None:
            row = Tool(slug=entry.slug, rating_source=SEEDED, needs_review=False)
            session.add(row)
        row.name = entry.name
        row.domains = [domain.lower() for domain in entry.domains]
        row.category = entry.category
        row.description = entry.description
        row.upstream_url = (
            f"{mock_upstream_url}/tools/{entry.slug}/v1" if entry.hosted_by_mock_upstream else None
        )
        if row.rating_source == SEEDED:
            row.status = entry.status.value
            row.risk_score = entry.risk_score
            row.risk_factors = entry.risk_factors.model_dump()
