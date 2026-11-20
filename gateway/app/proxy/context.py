from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

import httpx

from gateway.app.config import Settings
from gateway.app.core.conversation import vault_conversation
from gateway.app.core.interfaces import Inventory, Vault
from gateway.app.core.types import Principal
from gateway.app.events.writer import EventRecord
from gateway.app.proxy.inspection import Inspector


class EventSink(Protocol):
    async def write(self, record: EventRecord) -> int: ...

    async def mark_forwarded(self, trace_id: str, user_id: str) -> bool: ...


@dataclass(frozen=True)
class ProxyContext:
    """What the prompt path needs. Protocols, so tests can pass small fakes."""

    settings: Settings
    pseudonym_key: bytes
    inspector: Inspector
    vault: Vault
    inventory: Inventory
    events: EventSink
    http: httpx.AsyncClient

    def conversation(self, principal: Principal, given: str | None) -> tuple[str, str]:
        """The caller's conversation ID (a fresh one if none was given) and its vault name."""
        conversation_id = given or uuid4().hex
        return conversation_id, vault_conversation(principal, conversation_id, self.pseudonym_key)
