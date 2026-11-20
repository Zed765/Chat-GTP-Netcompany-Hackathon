"""Tells every gateway worker to reload a store (policy, protected data, inventory)."""

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from uuid import uuid4

from redis.asyncio import Redis

log = logging.getLogger(__name__)

CHANNEL = "aspida:reload"
Callback = Callable[[], Awaitable[None]]


class ReloadBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._worker = uuid4().hex
        self._callbacks: defaultdict[str, list[Callback]] = defaultdict(list)
        self._listener: asyncio.Task[None] | None = None

    def subscribe(self, topic: str, callback: Callback) -> None:
        self._callbacks[topic].append(callback)

    async def publish(self, topic: str) -> None:
        """Reload here before returning, so the caller's next request sees the change."""
        await self._run(topic)
        await self._redis.publish(CHANNEL, f"{self._worker}:{topic}")

    async def start(self) -> None:
        self._listener = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener

    async def _run(self, topic: str) -> None:
        for callback in self._callbacks[topic]:
            await callback()

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            worker, _, topic = message["data"].partition(":")
            if worker == self._worker:
                continue
            try:
                await self._run(topic)
            except Exception:
                log.exception("reload of %s failed", topic)
