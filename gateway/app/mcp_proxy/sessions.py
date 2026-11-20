"""What the gateway remembers about an agent session: its owner, its canary, whether
untrusted content has entered it, and the fingerprints of calls held for confirmation.

Everything lives in Redis with the vault's lifetime. No tool arguments or results are kept.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis

HELD_CALL_SECONDS = 15 * 60
CANARY_PREFIX = "ASPIDA-CANARY-"


@dataclass(frozen=True)
class SessionState:
    session_id: str
    owner: str
    canary: str
    tainted: bool
    taint_source: str | None


def call_fingerprint(tool: str, arguments: dict[str, Any]) -> str:
    """Identifies one exact call, so that only the call the user saw can be confirmed."""
    canonical = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class AgentSessions:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"aspida:agent:session:{session_id}"

    @staticmethod
    def _held_key(session_id: str, call_id: str) -> str:
        return f"aspida:agent:held:{session_id}:{call_id}"

    async def create(self, owner: str) -> SessionState:
        state = SessionState(
            session_id=uuid4().hex,
            owner=owner,
            canary=CANARY_PREFIX + secrets.token_hex(8),
            tainted=False,
            taint_source=None,
        )
        key = self._key(state.session_id)
        await self._redis.hset(key, mapping={"owner": owner, "canary": state.canary})
        await self._redis.expire(key, self._ttl)
        return state

    async def get(self, session_id: str) -> SessionState | None:
        # The gateway's Redis client decodes responses, so fields and values are text.
        stored = cast(dict[str, str], await self._redis.hgetall(self._key(session_id)))
        if not stored:
            return None
        source = stored.get("taint_source")
        return SessionState(
            session_id=session_id,
            owner=stored["owner"],
            canary=stored["canary"],
            tainted=source is not None,
            taint_source=source,
        )

    async def taint(self, session_id: str, source: str) -> None:
        """Mark the session tainted. The first source is kept: it is where the taint came from."""
        await self._redis.hsetnx(self._key(session_id), "taint_source", source)

    async def end(self, session_id: str) -> None:
        held = [key async for key in self._redis.scan_iter(self._held_key(session_id, "*"))]
        await self._redis.delete(self._key(session_id), *held)

    async def hold(self, session_id: str, call_id: str, fingerprint: str) -> None:
        await self._redis.set(
            self._held_key(session_id, call_id), fingerprint, ex=HELD_CALL_SECONDS
        )

    async def release(self, session_id: str, call_id: str, fingerprint: str) -> bool:
        """True once, and only for the exact call that was held."""
        held = await self._redis.getdel(self._held_key(session_id, call_id))
        return held is not None and secrets.compare_digest(str(held), fingerprint)
