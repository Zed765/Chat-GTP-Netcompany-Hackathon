"""Reversible pseudonymisation: placeholders out, real values back in."""

from gateway.app.core.deps import Deps
from gateway.app.vault.placeholders import (
    PLACEHOLDER_INSTRUCTION,
    SECRET_PLACEHOLDER,
    PlaceholderSpan,
    find_placeholders,
)
from gateway.app.vault.service import VaultService

__all__ = [
    "PLACEHOLDER_INSTRUCTION",
    "SECRET_PLACEHOLDER",
    "PlaceholderSpan",
    "VaultService",
    "build",
    "find_placeholders",
]

SECONDS_PER_HOUR = 3600


async def build(deps: Deps) -> VaultService:
    return VaultService(
        deps.redis, deps.keys.vault, deps.settings.vault_ttl_hours * SECONDS_PER_HOUR
    )
