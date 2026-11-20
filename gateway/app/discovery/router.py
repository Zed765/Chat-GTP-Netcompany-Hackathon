from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from gateway.app.core.auth import Admin, CurrentPrincipal
from gateway.app.core.services import Svc
from gateway.app.discovery.models import LogIngestion
from gateway.app.discovery.schemas import (
    IngestionOut,
    IngestionResult,
    LogKind,
    ToolOut,
    ToolUpdate,
)
from gateway.app.discovery.tools import tool_views

router = APIRouter(prefix="/api", tags=["inventory"])

MAX_LOG_BYTES = 50 * 1024 * 1024
RECENT_INGESTIONS = 100

_UNKNOWN_TOOL = HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tool")


@router.get("/tools")
async def list_tools(services: Svc, _: CurrentPrincipal, demo_only: bool = False) -> list[ToolOut]:
    async with services.db.session() as session:
        return await tool_views(session, demo_only=demo_only)


@router.get("/tools/{slug}")
async def get_tool(slug: str, services: Svc, _: CurrentPrincipal) -> ToolOut:
    async with services.db.session() as session:
        views = await tool_views(session, slug=slug)
    if not views:
        raise _UNKNOWN_TOOL
    return views[0]


@router.patch("/tools/{slug}")
async def update_tool(slug: str, body: ToolUpdate, services: Svc, _: Admin) -> ToolOut:
    view = await services.inventory.update(slug, body)
    if view is None:
        raise _UNKNOWN_TOOL
    return view


@router.get("/discovery/queue")
async def review_queue(services: Svc, _: Admin) -> list[ToolOut]:
    """AI tools found in logs that an analyst has not yet approved, tolerated or banned."""
    async with services.db.session() as session:
        return await tool_views(session, needs_review=True)


@router.post("/discovery/logs")
async def ingest_log(
    services: Svc,
    _: Admin,
    file: Annotated[UploadFile, File()],
    kind: Annotated[LogKind, Form()] = "squid",
) -> IngestionResult:
    """Ingest a Squid `access.log` or a DNS query log. The same content is ingested once."""
    content = await file.read(MAX_LOG_BYTES + 1)
    if len(content) > MAX_LOG_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The log is larger than 50 MB")
    if not content.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The log file is empty")
    return await services.inventory.ingest(content, file.filename or "upload", kind)


@router.get("/discovery/ingestions")
async def list_ingestions(services: Svc, _: Admin) -> list[IngestionOut]:
    statement = select(LogIngestion).order_by(LogIngestion.id.desc()).limit(RECENT_INGESTIONS)
    async with services.db.session() as session:
        rows = (await session.execute(statement)).scalars().all()
    return [IngestionOut.model_validate(row, from_attributes=True) for row in rows]
