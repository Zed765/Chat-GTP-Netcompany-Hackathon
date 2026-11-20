from datetime import UTC, date, datetime

import pytest

from gateway.app.discovery.logs import parse_dns, parse_squid, summarise

NINE = datetime(2026, 11, 10, 9, 0, 0, tzinfo=UTC)
EPOCH = f"{NINE.timestamp():.3f}"
PEER = "HIER_DIRECT/203.0.113.9"


def _squid(
    url: str = "chatgpt.com:443",
    *,
    time: str = EPOCH,
    elapsed: str = "245",
    client: str = "10.20.1.15",
    result: str = "TCP_TUNNEL/200",
    size: str = "5120",
    method: str = "CONNECT",
    user: str = "-",
) -> str:
    return f"{time}    {elapsed} {client} {result} {size} {method} {url} {user} {PEER} -"


def _team_of(*, user_id: str | None = None, ip: str | None = None) -> str:
    if user_id == "m.ioannou":
        return "Legal"
    return "Sales" if ip and ip.startswith("10.20.1.") else "Unknown"


def test_squid_connect_line() -> None:
    entry = parse_squid(_squid(user="m.ioannou"))
    assert entry is not None
    assert (entry.ts, entry.client_ip, entry.user, entry.host, entry.bytes_out) == (
        NINE,
        "10.20.1.15",
        "m.ioannou",
        "chatgpt.com",
        5120,
    )


def test_squid_url_line_without_a_user() -> None:
    line = _squid(
        "https://API.openai.com/v1/chat/completions", method="POST", result="TCP_MISS/200"
    )
    entry = parse_squid(line)
    assert entry is not None
    assert (entry.user, entry.host) == (None, "api.openai.com")


def test_squid_line_may_stop_after_the_url() -> None:
    entry = parse_squid(f"{EPOCH} 12 10.20.1.7 TCP_DENIED/403 0 CONNECT claude.ai:443")
    assert entry is not None and entry.host == "claude.ai" and entry.user is None


@pytest.mark.parametrize(
    "line",
    [
        "not a log line at all",
        f"{EPOCH} 245 10.20.1.15 TCP_TUNNEL/200 5120 CONNECT",
        _squid(time="yesterday"),
        _squid(time="1e400"),
        _squid(elapsed="fast"),
        _squid(client="not-an-address"),
        _squid(result="TCP_TUNNEL"),
        _squid(size="many"),
        _squid("http://[broken", method="GET"),
    ],
)
def test_malformed_squid_lines(line: str) -> None:
    assert parse_squid(line) is None


def test_dns_line() -> None:
    entry = parse_dns("2026-11-10T09:00:00Z 10.20.1.15 Chat.OpenAI.com. A")
    assert entry is not None
    assert (entry.ts, entry.client_ip, entry.user, entry.host, entry.bytes_out) == (
        NINE,
        "10.20.1.15",
        None,
        "chat.openai.com",
        0,
    )
    with_offset = parse_dns("2026-11-10T11:00:00+02:00 10.20.1.15 claude.ai AAAA")
    assert with_offset is not None and with_offset.ts == NINE
    naive = parse_dns("2026-11-10T09:00:00 10.20.1.15 claude.ai A")
    assert naive is not None and naive.ts == NINE


@pytest.mark.parametrize(
    "line",
    [
        "2026-11-10T09:00:00Z 10.20.1.15 claude.ai",
        "2026-11-10T09:00:00Z 10.20.1.15 claude.ai A extra",
        "10 November 10.20.1.15 claude.ai A",
        "2026-11-10T09:00:00Z somewhere claude.ai A",
        "2026-11-10T09:00:00Z 10.20.1.15 . A",
    ],
)
def test_malformed_dns_lines(line: str) -> None:
    assert parse_dns(line) is None


def test_summary_counts_lines_and_totals_per_host_team_and_day() -> None:
    late = f"{datetime(2026, 11, 11, 23, 30, tzinfo=UTC).timestamp():.3f}"
    log = "\n".join(
        [
            "# proxy log",
            _squid(size="5000", user="m.ioannou"),
            _squid(size="1000", user="m.ioannou"),
            _squid(size="700", client="10.20.1.16"),
            _squid(size="300", client="10.20.1.17"),
            _squid(size="40", client="10.20.1.16", time=late),
            _squid("claude.ai:443", client="192.168.9.9"),
            _squid("93.184.216.34:443"),
            "",
            "garbage line",
            "   ",
        ]
    )
    summary = summarise(log.encode(), "squid", _team_of)

    assert (summary.lines, summary.malformed) == (8, 1)
    # An address is not a domain, so it is read but belongs to no host.
    assert set(summary.hosts) == {"chatgpt.com", "claude.ai"}
    chatgpt = summary.hosts["chatgpt.com"]
    assert chatgpt.requests == 5
    assert (chatgpt.first_seen, chatgpt.last_seen.date()) == (NINE, date(2026, 11, 11))
    legal = chatgpt.cells["Legal", date(2026, 11, 10)]
    assert (legal.requests, legal.bytes_out, len(legal.people)) == (2, 6000, 1)
    sales = chatgpt.cells["Sales", date(2026, 11, 10)]
    assert (sales.requests, sales.bytes_out, len(sales.people)) == (2, 1000, 2)
    assert chatgpt.cells["Sales", date(2026, 11, 11)].requests == 1
    assert set(summary.hosts["claude.ai"].cells) == {("Unknown", date(2026, 11, 10))}


def test_bytes_that_are_not_text_are_counted_as_malformed() -> None:
    summary = summarise(b"\xff\xfe\x00 nonsense\n\x80\x81\n", "dns", _team_of)
    assert (summary.lines, summary.malformed, summary.hosts) == (2, 2, {})
