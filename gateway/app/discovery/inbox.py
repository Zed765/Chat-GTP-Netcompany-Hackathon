"""Watches the log inbox directory and ingests each file once it has stopped changing."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from gateway.app.discovery.schemas import LogKind

log = logging.getLogger(__name__)

KIND_BY_SUFFIX: dict[str, LogKind] = {".log": "squid", ".dns": "dns"}
POLL_SECONDS = 20.0

Ingest = Callable[[bytes, str, LogKind], Awaitable[object]]
_Stamp = tuple[int, int]


class InboxWatcher:
    def __init__(self, directory: Path, ingest: Ingest, interval_s: float = POLL_SECONDS) -> None:
        self._directory = directory
        self._ingest = ingest
        self._interval_s = interval_s
        self._last_scan: dict[Path, _Stamp] = {}
        self._ingested: dict[Path, _Stamp] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._poll(), name="log-inbox")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def scan(self) -> int:
        """Ingest the files that are the same size and age as at the previous scan, so a
        file still being written is left alone. Returns how many were handed over."""
        stamps = await asyncio.to_thread(self._stamps)
        settled = [
            path
            for path, stamp in stamps.items()
            if self._last_scan.get(path) == stamp and self._ingested.get(path) != stamp
        ]
        self._last_scan = stamps
        for path in settled:
            content = await asyncio.to_thread(path.read_bytes)
            await self._ingest(content, path.name, KIND_BY_SUFFIX[path.suffix])
            self._ingested[path] = stamps[path]
        return len(settled)

    def _stamps(self) -> dict[Path, _Stamp]:
        if not self._directory.is_dir():
            return {}
        stamps: dict[Path, _Stamp] = {}
        for path in sorted(self._directory.iterdir()):
            if path.suffix in KIND_BY_SUFFIX and path.is_file():
                stat = path.stat()
                stamps[path] = (stat.st_size, stat.st_mtime_ns)
        return stamps

    async def _poll(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception:
                log.exception("the log inbox scan failed; it will run again")
            await asyncio.sleep(self._interval_s)
