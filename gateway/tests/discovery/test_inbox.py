import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from gateway.app.core.deps import Deps
from gateway.app.discovery import InventoryService
from gateway.app.discovery.inbox import InboxWatcher
from gateway.app.discovery.models import LogIngestion
from gateway.app.discovery.schemas import LogKind

YESTERDAY = datetime.now(UTC) - timedelta(days=1)
SQUID_LINE = (
    f"{YESTERDAY.timestamp():.3f} 120 10.20.1.15 TCP_TUNNEL/200 900 CONNECT claude.ai:443 "
    "- HIER_DIRECT/203.0.113.9 -\n"
)
DNS_LINE = f"{YESTERDAY.isoformat()} 10.20.4.8 gemini.google.com. A\n"


class Recorder:
    def __init__(self) -> None:
        self.received: list[tuple[bytes, str, LogKind]] = []
        self.arrived = asyncio.Event()
        self.fail_next = False

    async def __call__(self, content: bytes, filename: str, kind: LogKind) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the database is away")
        self.received.append((content, filename, kind))
        self.arrived.set()


async def test_missing_directory_is_fine(tmp_path: Path) -> None:
    recorder = Recorder()
    watcher = InboxWatcher(tmp_path / "not-there", recorder)
    assert await watcher.scan() == 0
    assert recorder.received == []


async def test_a_file_is_ingested_once_it_stops_changing(tmp_path: Path) -> None:
    recorder = Recorder()
    watcher = InboxWatcher(tmp_path, recorder)
    (tmp_path / "access.log").write_text(SQUID_LINE)
    (tmp_path / "queries.dns").write_text(DNS_LINE)
    (tmp_path / "README.md").write_text("Drop logs here.")
    (tmp_path / "archive.log").mkdir()

    # First sight: the files may still be growing.
    assert await watcher.scan() == 0
    assert await watcher.scan() == 2
    assert recorder.received == [
        (SQUID_LINE.encode(), "access.log", "squid"),
        (DNS_LINE.encode(), "queries.dns", "dns"),
    ]
    assert await watcher.scan() == 0

    grown = tmp_path / "access.log"
    grown.write_text(SQUID_LINE * 2)
    os.utime(grown, ns=(1, grown.stat().st_mtime_ns + 1_000_000))
    assert await watcher.scan() == 0
    assert await watcher.scan() == 1
    assert recorder.received[-1] == ((SQUID_LINE * 2).encode(), "access.log", "squid")


async def test_a_failed_ingestion_is_tried_again(tmp_path: Path) -> None:
    recorder = Recorder()
    watcher = InboxWatcher(tmp_path, recorder)
    (tmp_path / "access.log").write_text(SQUID_LINE)
    await watcher.scan()
    recorder.fail_next = True
    with pytest.raises(RuntimeError):
        await watcher.scan()
    assert await watcher.scan() == 1
    assert len(recorder.received) == 1


async def test_polling_starts_and_stops_cleanly(tmp_path: Path) -> None:
    recorder = Recorder()
    watcher = InboxWatcher(tmp_path, recorder, interval_s=0.01)
    (tmp_path / "access.log").write_text(SQUID_LINE)
    watcher.start()
    await asyncio.wait_for(recorder.arrived.wait(), timeout=5)
    await watcher.stop()
    await watcher.stop()
    tasks = [task for task in asyncio.all_tasks() if task.get_name() == "log-inbox"]
    assert tasks == []
    assert len(recorder.received) == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_dropped_files_go_through_the_same_ingestion(
    inventory: InventoryService, deps: Deps
) -> None:
    # The service polls the inbox in the background; that would race the scans below.
    await inventory.aclose()
    inbox = deps.settings.log_inbox_dir
    inbox.mkdir()
    (inbox / "access.log").write_text(SQUID_LINE * 3)
    (inbox / "queries.dns").write_text(DNS_LINE)

    assert await inventory.scan_inbox() == 0
    assert await inventory.scan_inbox() == 2

    async with deps.db.session() as session:
        ingested = (await session.execute(select(LogIngestion).order_by(LogIngestion.id))).scalars()
        assert [(row.filename, row.kind, row.matched) for row in ingested] == [
            ("access.log", "squid", 3),
            ("queries.dns", "dns", 1),
        ]
    # A restart reads the folder again; the content hash stops a second count.
    restarted = InventoryService(deps)
    await restarted.scan_inbox()
    assert await restarted.scan_inbox() == 2
    async with deps.db.session() as session:
        assert len((await session.execute(select(LogIngestion))).all()) == 2
