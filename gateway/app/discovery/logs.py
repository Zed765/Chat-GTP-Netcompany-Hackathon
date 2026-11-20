"""Parses proxy and DNS logs and totals them per host, team and day.

Squid native format: `time.ms elapsed client code/status bytes method URL user peer type`.
DNS query log: `ISO-timestamp client-ip qname qtype`.
User IDs and client addresses are used to find the team and to count people; they are
never kept.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from ipaddress import ip_address
from typing import Protocol

from gateway.app.discovery.index import host_of, is_ip
from gateway.app.discovery.schemas import LogKind

_SQUID_MIN_FIELDS = 7
_DNS_FIELDS = 4


class TeamOf(Protocol):
    def __call__(self, *, user_id: str | None = None, ip: str | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class LogLine:
    ts: datetime
    client_ip: str
    user: str | None
    host: str
    bytes_out: int


@dataclass(slots=True)
class Cell:
    """Traffic to one host from one team on one day."""

    requests: int = 0
    bytes_out: int = 0
    people: set[str] = field(default_factory=set)

    def add(self, other: "Cell") -> None:
        self.requests += other.requests
        self.bytes_out += other.bytes_out
        self.people |= other.people


@dataclass(slots=True)
class HostUsage:
    first_seen: datetime
    last_seen: datetime
    requests: int = 0
    cells: dict[tuple[str, date], Cell] = field(default_factory=dict)

    def add(self, other: "HostUsage") -> None:
        self.first_seen = min(self.first_seen, other.first_seen)
        self.last_seen = max(self.last_seen, other.last_seen)
        self.requests += other.requests
        for key, cell in other.cells.items():
            self.cells.setdefault(key, Cell()).add(cell)


@dataclass(slots=True)
class LogSummary:
    lines: int = 0
    malformed: int = 0
    hosts: dict[str, HostUsage] = field(default_factory=dict)


def parse_squid(line: str) -> LogLine | None:
    fields = line.split()
    if len(fields) < _SQUID_MIN_FIELDS or "/" not in fields[3]:
        return None
    try:
        ts = datetime.fromtimestamp(float(fields[0]), UTC)
        int(fields[1])
        ip_address(fields[2])
        size = int(fields[4])
    except (ValueError, OverflowError, OSError):
        return None
    user = fields[7] if len(fields) > _SQUID_MIN_FIELDS and fields[7] != "-" else None
    host = host_of(fields[6])
    return LogLine(ts, fields[2], user, host, max(size, 0)) if host else None


def parse_dns(line: str) -> LogLine | None:
    fields = line.split()
    if len(fields) != _DNS_FIELDS:
        return None
    try:
        ts = datetime.fromisoformat(fields[0])
        ip_address(fields[1])
    except ValueError:
        return None
    host = host_of(fields[2])
    if not host:
        return None
    return LogLine(ts if ts.tzinfo else ts.replace(tzinfo=UTC), fields[1], None, host, 0)


PARSERS: dict[LogKind, Callable[[str], LogLine | None]] = {"squid": parse_squid, "dns": parse_dns}


def summarise(content: bytes, kind: LogKind, team_of: TeamOf) -> LogSummary:
    """Total a log file. Blank lines and `#` comments are skipped; bad lines are counted."""
    parse = PARSERS[kind]
    summary = LogSummary()
    for raw in content.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        summary.lines += 1
        entry = parse(line)
        if entry is None:
            summary.malformed += 1
        elif not is_ip(entry.host):
            _count(summary, entry, team_of(user_id=entry.user, ip=entry.client_ip))
    return summary


def _count(summary: LogSummary, entry: LogLine, team: str) -> None:
    usage = summary.hosts.get(entry.host)
    if usage is None:
        usage = summary.hosts[entry.host] = HostUsage(entry.ts, entry.ts)
    usage.first_seen = min(usage.first_seen, entry.ts)
    usage.last_seen = max(usage.last_seen, entry.ts)
    usage.requests += 1
    cell = usage.cells.setdefault((team, entry.ts.astimezone(UTC).date()), Cell())
    cell.requests += 1
    cell.bytes_out += entry.bytes_out
    cell.people.add(entry.user or entry.client_ip)
