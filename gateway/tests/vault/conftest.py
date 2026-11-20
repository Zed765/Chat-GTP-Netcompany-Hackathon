import pytest
from redis.asyncio import Redis

from gateway.app.vault import VaultService
from gateway.tests.vault.helpers import TTL_SECONDS, VAULT_KEY


@pytest.fixture
def vault(redis: Redis) -> VaultService:
    return VaultService(redis, VAULT_KEY, TTL_SECONDS)
