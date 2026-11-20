"""Small key-value settings kept in the database, such as the retention period."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from gateway.app.db.session import Database
from gateway.app.privacy.models import Setting

RETENTION_DAYS = "retention_days"
SEED_STEPS = "seed_steps"
STORE_SNIPPETS = "store_snippets"


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str, default: Any) -> Any:
        async with self._db.session() as session:
            row = await session.get(Setting, key)
        return default if row is None else row.value

    async def put(self, key: str, value: Any) -> None:
        statement = insert(Setting).values(key=key, value=value)
        async with self._db.session() as session:
            await session.execute(
                statement.on_conflict_do_update(index_elements=[Setting.key], set_={"value": value})
            )
