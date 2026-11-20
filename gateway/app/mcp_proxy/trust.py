"""How far the agent's systems are trusted, as an admin sets it."""

from dataclasses import dataclass
from typing import Self

from gateway.app.config import Settings
from gateway.app.privacy.store import SettingsStore

AGENT_TRUST = "agent_trust"
RELOAD_TOPIC = "agent-trust"


@dataclass(frozen=True)
class AgentTrust:
    """What a trusted system returns is believed, and what is sent to it may be real. Mail is
    the exception when it delivers: a message is judged by the domains of its recipients."""

    servers: frozenset[str]
    mail_domains: frozenset[str]

    @classmethod
    def configured(cls, settings: Settings) -> Self:
        """The deployment's own choice, in force until an admin makes another."""
        return cls(
            frozenset(settings.trusted_mcp_servers),
            frozenset({settings.internal_mail_domain.lower()}),
        )


class AgentTrustStore:
    """The admin's choice, read once and again whenever it is saved, on any worker."""

    def __init__(self, store: SettingsStore, configured: AgentTrust) -> None:
        self._store = store
        self._configured = configured
        self.current = configured

    async def reload(self) -> None:
        saved = await self._store.get(AGENT_TRUST, None)
        self.current = (
            self._configured
            if saved is None
            else AgentTrust(frozenset(saved["servers"]), frozenset(saved["mail_domains"]))
        )

    async def save(self, trust: AgentTrust) -> None:
        await self._store.put(
            AGENT_TRUST,
            {"servers": sorted(trust.servers), "mail_domains": sorted(trust.mail_domains)},
        )
        self.current = trust
