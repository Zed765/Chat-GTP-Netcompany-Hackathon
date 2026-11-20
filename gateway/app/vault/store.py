"""The vault in Redis: two hashes per conversation, both expiring together.

- `…:links` is the forward mapping, from a mention to its placeholder. Its fields are keyed
  hashes of the lookup keys, so masking needs one `HMGET` and no decryption.
- `…:values` is the reverse mapping, from a placeholder to its AES-GCM sealed value.

Every call is one round trip, and every call renews the lifetime of both hashes.
"""

from collections.abc import Collection, Mapping

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.typing import EncodableT, FieldT

from gateway.app.vault.linking import LinkKey
from gateway.app.vault.sealing import Sealer

DEFAULT_PREFIX = "aspida:vault"


class VaultStore:
    def __init__(
        self, redis: Redis, sealer: Sealer, ttl_seconds: int, prefix: str = DEFAULT_PREFIX
    ) -> None:
        self._redis = redis
        self._sealer = sealer
        self._ttl = ttl_seconds
        self._prefix = prefix

    def _keys(self, conversation_id: str) -> tuple[str, str]:
        """The conversation ID holds text the client chose, so only its keyed hash reaches
        Redis. The braces keep both hashes in one cluster slot."""
        name = f"{self._prefix}:{{{self._sealer.token('conversation', conversation_id)}}}"
        return f"{name}:links", f"{name}:values"

    def _field(self, conversation_id: str, entry: LinkKey) -> str:
        return self._sealer.token("link", conversation_id, *entry)

    def _renew(self, pipe: Pipeline, conversation_id: str) -> None:
        for key in self._keys(conversation_id):
            pipe.expire(key, self._ttl)

    async def read_links(
        self, conversation_id: str, entries: Collection[LinkKey]
    ) -> dict[LinkKey, str]:
        """The entries of the forward mapping that exist, out of those asked for."""
        links, _ = self._keys(conversation_id)
        wanted = list(entries)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.hmget(links, [self._field(conversation_id, entry) for entry in wanted])
            self._renew(pipe, conversation_id)
            found, *_ = await pipe.execute()
        return {entry: value for entry, value in zip(wanted, found, strict=True) if value}

    async def write(
        self, conversation_id: str, links: Mapping[LinkKey, str], values: Mapping[str, str]
    ) -> None:
        """Add to both mappings in one transaction. `values` maps new placeholders to the
        plain values they restore to; they are sealed here."""
        links_key, values_key = self._keys(conversation_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            if links:
                fields: dict[FieldT, EncodableT] = {
                    self._field(conversation_id, entry): value for entry, value in links.items()
                }
                pipe.hset(links_key, mapping=fields)
            if values:
                sealed: dict[FieldT, EncodableT] = {
                    placeholder: self._sealer.seal(conversation_id, placeholder, value)
                    for placeholder, value in values.items()
                }
                pipe.hset(values_key, mapping=sealed)
            self._renew(pipe, conversation_id)
            await pipe.execute()

    async def read_values(self, conversation_id: str) -> dict[str, str]:
        """Every placeholder of the conversation with its value. One that does not open
        (another key, or copied from another conversation) is left out."""
        _, values_key = self._keys(conversation_id)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.hgetall(values_key)
            self._renew(pipe, conversation_id)
            sealed, *_ = await pipe.execute()
        opened = {
            placeholder: self._sealer.open(conversation_id, placeholder, value)
            for placeholder, value in sealed.items()
        }
        return {placeholder: value for placeholder, value in opened.items() if value is not None}

    async def placeholders(self, conversation_id: str) -> list[str]:
        _, values_key = self._keys(conversation_id)
        return [str(field) for field in await self._redis.hkeys(values_key)]

    async def delete(self, conversation_id: str) -> None:
        await self._redis.delete(*self._keys(conversation_id))
