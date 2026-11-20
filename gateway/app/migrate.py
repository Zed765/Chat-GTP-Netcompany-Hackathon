"""Bring the database to the latest schema. Runs before the gateway starts."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from gateway.app.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def upgrade(database_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    upgrade(get_settings().database_url)
