"""Deletes events older than the retention period, once a day."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import CursorResult, delete

from gateway.app.db.session import Database
from gateway.app.events.models import Event
from gateway.app.privacy.store import RETENTION_DAYS, SettingsStore

log = logging.getLogger(__name__)

PURGE_INTERVAL_S = 24 * 60 * 60


class Retention:
    def __init__(self, db: Database, store: SettingsStore, default_days: int) -> None:
        self._db = db
        self._store = store
        self._default_days = default_days
        self._task: asyncio.Task[None] | None = None

    async def days(self) -> int:
        return int(await self._store.get(RETENTION_DAYS, self._default_days))

    async def purge(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=await self.days())
        async with self._db.session() as session:
            result = await session.execute(delete(Event).where(Event.ts < cutoff))
        return int(result.rowcount) if isinstance(result, CursorResult) else 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self.purge()
            except Exception:
                log.exception("retention purge failed")
            await asyncio.sleep(PURGE_INTERVAL_S)
