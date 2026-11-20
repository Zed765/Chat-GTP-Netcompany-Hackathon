from dataclasses import dataclass

from redis.asyncio import Redis

from gateway.app.config import Settings
from gateway.app.core.keys import Keys
from gateway.app.core.reload import ReloadBus
from gateway.app.db.session import Database
from gateway.app.llm.client import LLM
from gateway.app.privacy.directory import Directory


@dataclass(frozen=True)
class Deps:
    """What every module's `build` function receives."""

    settings: Settings
    keys: Keys
    db: Database
    redis: Redis
    bus: ReloadBus
    llm: LLM
    directory: Directory
