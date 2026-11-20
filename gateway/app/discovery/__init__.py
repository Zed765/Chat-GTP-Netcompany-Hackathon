import asyncio

from sqlalchemy import select

from gateway.app.core.deps import Deps
from gateway.app.core.types import ToolRef, ToolStatus
from gateway.app.discovery.catalogue import read_catalogue, sync_catalogue
from gateway.app.discovery.inbox import InboxWatcher
from gateway.app.discovery.index import ToolIndex, host_of
from gateway.app.discovery.ingest import ingest_log
from gateway.app.discovery.models import Tool
from gateway.app.discovery.schemas import IngestionResult, LogKind, ToolOut, ToolUpdate
from gateway.app.discovery.tools import apply_update, tool_views

UNNAMED_TOOL = "unnamed-tool"
_SLUG_CHARS = 120


class InventoryService:
    """Implements `core.interfaces.Inventory`."""

    def __init__(self, deps: Deps) -> None:
        self._deps = deps
        self._index = ToolIndex()
        self._inbox = InboxWatcher(deps.settings.log_inbox_dir, self.ingest)

    async def load_catalogue(self) -> None:
        """Load the default catalogue of AI tools. Safe to run on every start."""
        entries = await asyncio.to_thread(read_catalogue, self._deps.settings.defaults_dir)
        async with self._deps.db.session() as session:
            await sync_catalogue(session, entries, self._deps.settings.mock_upstream_url)
        await self.reload()

    async def reload(self) -> None:
        async with self._deps.db.session() as session:
            rows = (await session.execute(select(Tool))).scalars().all()
        self._index = ToolIndex.of(rows)

    async def resolve(self, tool: str) -> ToolRef:
        """Look a tool up by slug or domain. An unseen one comes back as `unknown`."""
        found = self._index.find(tool)
        if found is not None:
            return found
        name = host_of(tool) or tool.strip() or UNNAMED_TOOL
        return ToolRef(slug=name.lower()[:_SLUG_CHARS], name=name, status=ToolStatus.UNKNOWN)

    async def approved_alternatives(self, category: str | None) -> list[ToolRef]:
        return self._index.approved_alternatives(category)

    def tools(self) -> list[ToolRef]:
        return list(self._index.by_slug.values())

    async def update(self, slug: str, change: ToolUpdate) -> ToolOut | None:
        """Apply an analyst's change; the next policy decision sees the new status."""
        async with self._deps.db.session() as session:
            statement = select(Tool).where(Tool.slug == slug).with_for_update()
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                return None
            apply_update(row, change)
            await session.flush()
            [view] = await tool_views(session, slug=slug)
        await self._deps.bus.publish("inventory")
        return view

    async def ingest(self, content: bytes, filename: str, kind: LogKind) -> IngestionResult:
        return await ingest_log(self._deps, self._index, content, filename, kind)

    def watch_inbox(self) -> None:
        """Start polling the log inbox directory. `aclose` stops it."""
        self._inbox.start()

    async def scan_inbox(self) -> int:
        return await self._inbox.scan()

    async def aclose(self) -> None:
        await self._inbox.stop()


async def build(deps: Deps) -> InventoryService:
    inventory = InventoryService(deps)
    await inventory.load_catalogue()
    deps.bus.subscribe("inventory", inventory.reload)
    inventory.watch_inbox()
    return inventory
