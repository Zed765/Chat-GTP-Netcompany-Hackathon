from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from gateway.app.core.auth import issue_token
from gateway.app.core.deps import Deps
from gateway.app.core.types import Principal
from gateway.app.discovery import InventoryService
from gateway.app.policy import PolicyEngine, build
from gateway.app.policy.models import PolicyVersion
from gateway.app.policy.router import router


@pytest.fixture
async def engine(deps: Deps) -> AsyncIterator[PolicyEngine]:
    """An engine on an empty `policy_versions` table, so it starts from the default policy.

    Its inventory is left empty: these tests are about the policy, not about tools.
    """
    async with deps.db.session() as session:
        await session.execute(delete(PolicyVersion))
    yield await build(deps, InventoryService(deps))
    async with deps.db.session() as session:
        await session.execute(delete(PolicyVersion))


@pytest.fixture
async def api(deps: Deps, engine: PolicyEngine) -> AsyncIterator[AsyncClient]:
    """The policy routes over HTTP, with only the services they use."""
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(
        keys=deps.keys,
        db=deps.db,
        llm=deps.llm,
        directory=deps.directory,
        policy=engine,
        inventory=InventoryService(deps),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway") as client:
        yield client


@pytest.fixture
def signed_in(deps: Deps) -> Callable[[Principal], dict[str, str]]:
    """Request headers that sign a demo user in."""

    def headers(user: Principal) -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_token(user, deps.keys.session, hours=1)}"}

    return headers
