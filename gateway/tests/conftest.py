"""Shared fixtures. Integration tests need `make test-deps` (Postgres and Redis)."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gateway.app.config import Settings
from gateway.app.core.auth import issue_token
from gateway.app.core.deps import Deps
from gateway.app.core.keys import Keys, load_keys
from gateway.app.core.reload import ReloadBus
from gateway.app.core.services import Services
from gateway.app.core.types import Principal
from gateway.app.db.session import Database
from gateway.app.main import create_app
from gateway.app.migrate import upgrade
from gateway.app.privacy.directory import Directory
from gateway.tests.doubles import HASH_THRESHOLDS, FakeLLM

REPO = Path(__file__).resolve().parents[2]
# The read-only role is shared by every database on the test server, so its password is fixed.
READONLY_PASSWORD = "aspida-test-readonly"
TEST_REDIS = os.environ.get("ASPIDA_TEST_REDIS_URL", "redis://127.0.0.1:56379/0")
TEST_SERVER = os.environ.get(
    "ASPIDA_TEST_DATABASE_URL", "postgresql+asyncpg://aspida:aspida@127.0.0.1:55432"
)


@pytest.fixture(scope="session")
def keys_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One set of generated keys for the session, as one deployment has."""
    return tmp_path_factory.mktemp("keys")


@pytest.fixture(scope="session")
def keys(keys_dir: Path) -> Keys:
    """The same keys the in-process gateway loads."""
    return load_keys(keys_dir)


@pytest.fixture
def settings(keys_dir: Path) -> Settings:
    return Settings(
        readonly_db_password=READONLY_PASSWORD,
        keys_dir=keys_dir,
        defaults_dir=REPO / "defaults",
        policies_dir=REPO / "policies",
    )


@pytest.fixture
def llm(settings: Settings) -> Iterator[FakeLLM]:
    """The model double behind `deps` and `api`. A test scripts the answers it needs."""
    fake = FakeLLM(settings)
    yield fake
    assert not fake.unscripted, f"model calls with no scripted answer: {fake.unscripted}"


class Api:
    """Calls the gateway in process, signed in as one of the demo users."""

    def __init__(self, client: httpx.AsyncClient, services: Services) -> None:
        self.client = client
        self.services = services

    def as_(self, user: Principal) -> dict[str, str]:
        settings = self.services.settings
        token = issue_token(user, self.services.keys.session, settings.session_hours)
        return {"Authorization": f"Bearer {token}"}


async def _admin(statement: str) -> None:
    engine = create_async_engine(f"{TEST_SERVER}/aspida", isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(statement))
    await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A fresh, fully migrated database for this test session."""
    name = f"test_{uuid4().hex[:12]}"
    try:
        asyncio.run(_admin(f"CREATE DATABASE {name}"))
    except OSError:
        pytest.skip("Postgres is not running; start it with `make test-deps`")
    url = f"{TEST_SERVER}/{name}"
    upgrade(url)
    yield url
    asyncio.run(_admin(f"DROP DATABASE {name} WITH (FORCE)"))


@asynccontextmanager
async def running_gateway(settings: Settings, llm: FakeLLM) -> AsyncIterator[Api]:
    """The whole gateway, started in process on the model double and stopped on exit."""
    app = create_app(settings, llm)
    started, finished = asyncio.Event(), asyncio.Event()

    async def run_lifespan() -> None:
        # One task enters and leaves the lifespan, as a server does; anyio requires it.
        async with app.router.lifespan_context(app):
            started.set()
            await finished.wait()

    lifespan = asyncio.create_task(run_lifespan())
    waiting = asyncio.create_task(started.wait())
    await asyncio.wait({lifespan, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if lifespan.done():
        waiting.cancel()
        lifespan.result()
    app.state.services.detector.settings = HASH_THRESHOLDS
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            yield Api(client, app.state.services)
    finally:
        finished.set()
        await lifespan


@pytest.fixture
async def api(settings: Settings, database_url: str, llm: FakeLLM) -> AsyncIterator[Api]:
    """The gateway against the test database and the test Redis."""
    wired = settings.model_copy(update={"database_url": database_url, "redis_url": TEST_REDIS})
    async with running_gateway(wired, llm) as running:
        yield running


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    database = Database(database_url)
    yield database
    await database.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def deps(settings: Settings, keys: Keys, db: Database, redis: Redis, llm: FakeLLM) -> Deps:
    """What a module's `build` receives, with the model double in place of OpenAI."""
    return Deps(
        settings=settings,
        keys=keys,
        db=db,
        redis=redis,
        bus=ReloadBus(redis),
        llm=llm,
        directory=Directory(db, keys.pseudonym),
    )
