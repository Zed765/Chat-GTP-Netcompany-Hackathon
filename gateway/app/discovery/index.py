"""In-memory lookup of inventory tools by slug or by domain, including subdomains."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from urllib.parse import urlsplit

from gateway.app.core.types import ToolRef, ToolStatus
from gateway.app.discovery.models import Tool

GENERAL_PURPOSE_CATEGORY = "chat assistant"
MAX_ALTERNATIVES = 3


def host_of(value: str) -> str:
    """The host in a URL, a `host:port` pair or a DNS name; empty when there is none."""
    text = value.strip()
    try:
        host = urlsplit(text if "://" in text else f"//{text}").hostname
    except ValueError:
        return ""
    return (host or "").rstrip(".")


def is_ip(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def with_parents(host: str) -> Iterator[str]:
    """`a.b.example.com` yields itself, `b.example.com` and `example.com`."""
    labels = host.split(".")
    for start in range(max(len(labels) - 1, 1)):
        yield ".".join(labels[start:])


def tool_ref(row: Tool) -> ToolRef:
    return ToolRef(
        slug=row.slug,
        name=row.name,
        status=ToolStatus(row.status),
        category=row.category,
        upstream_url=row.upstream_url,
    )


@dataclass(frozen=True)
class ToolIndex:
    by_slug: Mapping[str, ToolRef] = field(default_factory=dict)
    by_domain: Mapping[str, ToolRef] = field(default_factory=dict)
    risk: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def of(cls, rows: Iterable[Tool]) -> "ToolIndex":
        by_slug: dict[str, ToolRef] = {}
        by_domain: dict[str, ToolRef] = {}
        risk: dict[str, int] = {}
        for row in rows:
            ref = tool_ref(row)
            by_slug[row.slug] = ref
            risk[row.slug] = row.risk_score
            for domain in row.domains:
                by_domain[domain.lower()] = ref
        return cls(by_slug, by_domain, risk)

    def find(self, tool: str) -> ToolRef | None:
        """By slug first, then by the most specific domain that matches."""
        key = tool.strip().lower()
        if key in self.by_slug:
            return self.by_slug[key]
        return self.find_host(host_of(key))

    def find_host(self, host: str) -> ToolRef | None:
        return next(
            (self.by_domain[name] for name in with_parents(host) if name in self.by_domain), None
        )

    def approved_alternatives(self, category: str | None) -> list[ToolRef]:
        """Approved tools of the same category, then general-purpose ones.

        Within each group, tools the gateway can forward to come first, then lower risk.
        """

        def order(ref: ToolRef) -> tuple[bool, bool, int, str]:
            return (
                ref.category != category,
                ref.upstream_url is None,
                self.risk[ref.slug],
                ref.name.lower(),
            )

        suitable = [
            ref
            for ref in self.by_slug.values()
            if ref.status is ToolStatus.APPROVED
            and ref.category in (category, GENERAL_PURPOSE_CATEGORY)
        ]
        return sorted(suitable, key=order)[:MAX_ALTERNATIVES]
