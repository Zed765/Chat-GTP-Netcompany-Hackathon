import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from gateway.app.config import Settings
from gateway.app.core.auth import DEMO_USERS
from gateway.app.db.session import Database
from gateway.tests.conftest import REPO, Api

ADMIN = DEMO_USERS[1]
EMPLOYEE = DEMO_USERS[0]


@pytest.fixture(scope="session")
def pack_without_exemplars(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("defaults")
    for name in ("terms.yaml", "patterns.yaml", "tools.yaml"):
        shutil.copy(REPO / "defaults" / name, directory / name)
    return directory


@pytest.fixture
def settings(settings: Settings, pack_without_exemplars: Path) -> Settings:
    """The default pack without category exemplars, so a test sees only the documents it
    uploads. The exemplar tests bring their own."""
    return settings.model_copy(update={"defaults_dir": pack_without_exemplars})


@pytest.fixture
async def clean_stores(db: Database) -> None:
    """The test starts from the default pack alone, with every default row switched on.
    Request it through `pytest.mark.usefixtures`, so it runs before the gateway is built."""
    async with db.session() as session:
        for table in ("protected_terms", "custom_patterns", "protected_documents"):
            await session.execute(text(f"DELETE FROM {table} WHERE source <> 'default'"))  # noqa: S608
            await session.execute(text(f"UPDATE {table} SET enabled = true"))  # noqa: S608
        await session.execute(text("DELETE FROM default_switches"))


@pytest.fixture
def analyst(api: Api) -> dict[str, str]:
    return api.as_(ADMIN)
