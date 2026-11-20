"""Synthetic proxy and DNS logs: traffic to known AI tools, to AI services the inventory has
never seen, and to ordinary sites. The formats are those in `contracts/README.md`."""

import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from random import Random

from seeder.activity.profiles import Tool, team_tools
from seeder.activity.timeline import Timeline
from seeder.world import Employee, World

# AI services that are not in the inventory, with the teams that use them.
UNKNOWN_AI_HOSTS: dict[str, tuple[str, ...]] = {
    "app.quillmind.example": ("Sales", "HR"),
    "chat.lexsage.example": ("Legal",),
    "api.promptforge.example": ("Engineering",),
    "www.voxscribe.example": ("Customer Support", "Sales"),
    "app.pixelmuse.example": ("Sales",),
    "sumly.example": ("Finance", "Legal"),
    "codewhisk.example": ("Engineering",),
}
ORDINARY_HOSTS = (
    "intranet.aspida-demo.example",
    "mail.aspida-demo.example",
    "docs.teamwiki.example",
    "www.ferrytickets.example",
    "news.imerisia-press.example",
    "weather.kairos-now.example",
    "maps.cityroutes.example",
    "www.ebanking-portal.example",
    "shop.agora-market.example",
    "video.streamcast.example",
    "cdn.fastassets.example",
    "updates.softvendor.example",
)
AI_VISITS = (80, 160)
UNKNOWN_VISITS = (3, 10)
ORDINARY_VISITS = (60, 110)


@dataclass(frozen=True)
class Visit:
    at: datetime
    employee: Employee
    host: str


def registrable_domain(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def plan_visits(
    world: World, inventory: Sequence[Tool], timeline: Timeline, rng: Random
) -> list[Visit]:
    visits = []
    for employee in world.employees:
        tools = {
            tool: w for tool, w in team_tools(employee.team, inventory).items() if tool.domains
        }
        unknown = [host for host, teams in UNKNOWN_AI_HOSTS.items() if employee.team in teams]
        hosts = [
            rng.choice(tool.domains)
            for tool in rng.choices(
                list(tools), weights=list(tools.values()), k=rng.randrange(*AI_VISITS)
            )
        ]
        hosts += rng.choices(unknown, k=rng.randrange(*UNKNOWN_VISITS)) if unknown else []
        hosts += rng.choices(ORDINARY_HOSTS, k=rng.randrange(*ORDINARY_VISITS))
        moments = timeline.sample(rng, len(hosts), timeline.start, timeline.now)
        rng.shuffle(hosts)
        visits += [Visit(at, employee, host) for at, host in zip(moments, hosts, strict=True)]
    return sorted(visits, key=lambda visit: visit.at)


def _peer(host: str) -> str:
    """A stable address in a documentation range, so no real server is named."""
    return f"203.0.113.{zlib.crc32(host.encode()) % 254 + 1}"


def squid_log(visits: Sequence[Visit], rng: Random) -> str:
    """Squid's native format: time elapsed client code/status bytes method URL user peer type."""
    lines = [
        f"{visit.at.timestamp():.3f} {rng.randrange(40, 9000):6d} {visit.employee.ip} "
        f"TCP_TUNNEL/200 {rng.randrange(900, 48000)} CONNECT {visit.host}:443 "
        f"{visit.employee.user_id} HIER_DIRECT/{_peer(visit.host)} -"
        for visit in visits
    ]
    return "\n".join(lines) + "\n"


def dns_log(visits: Sequence[Visit]) -> str:
    """One `ISO-timestamp client-ip qname qtype` line for each lookup."""
    lines = [
        f"{visit.at.strftime('%Y-%m-%dT%H:%M:%SZ')} {visit.employee.ip} {visit.host} A"
        for visit in visits
    ]
    return "\n".join(lines) + "\n"
