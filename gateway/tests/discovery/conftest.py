import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from gateway.app.config import Settings
from gateway.app.core.auth import issue_token
from gateway.app.core.deps import Deps
from gateway.app.core.types import Principal
from gateway.app.discovery import InventoryService, build
from gateway.app.discovery.router import router
from gateway.app.policy import PolicyEngine
from gateway.app.policy import build as build_policy
from gateway.app.privacy.directory import DirectoryImport, DirectoryUserIn, NetworkIn
from gateway.tests.doubles import FakeLLM

SITES = {
    "notesly.example": {
        "title": "Notesly AI - Meeting notes that write themselves",
        "description": "An AI meeting assistant that records, transcribes and summarises "
        "your calls with a large language model. SOC 2 certified, with single sign-on.",
    },
    "promptforge.example": {
        "title": "PromptForge",
        "description": "Generative AI chatbot for drafting emails and reports. Conversations "
        "are used to train and improve our models for every user.",
    },
    "dailyherald.example": {
        "title": "The Daily Herald",
        "description": "News site with articles, analysis and opinion about politics, "
        "business and technology, including the latest on AI regulation.",
    },
    "parcelpost.example": {
        "title": "ParcelPost | Track your delivery",
        "description": "Online shop deliveries: track a parcel, book a courier, arrange returns.",
    },
}


NOT_AN_AI_SERVICE = {
    "is_ai_service": False,
    "category": "other AI service",
    "summary": "A website.",
    "reason": "The description names no AI service.",
    "trains_on_customer_data": None,
    "retention_days": None,
    "data_residency": None,
    "enterprise_terms": None,
    "sso": None,
    "certifications": [],
}
# What a careful reader makes of `SITES`: two AI services, each with what its text states.
VERDICTS = {
    "notesly.example": NOT_AN_AI_SERVICE
    | {
        "is_ai_service": True,
        "category": "meeting assistant",
        "summary": "Records, transcribes and summarises calls.",
        "reason": "The description calls it an AI meeting assistant.",
        "sso": True,
        "certifications": ["SOC 2"],
    },
    "promptforge.example": NOT_AN_AI_SERVICE
    | {
        "is_ai_service": True,
        "category": "chat assistant",
        "summary": "Drafts emails and reports.",
        "reason": "The description calls it a generative AI chatbot.",
        "trains_on_customer_data": True,
    },
}


def site_verdict(text: str) -> dict[str, object]:
    """The model's answer about the site a classification call names in its first line."""
    return VERDICTS.get(text.splitlines()[0].removeprefix("Domain: "), NOT_AN_AI_SERVICE)


@pytest.fixture
def llm(llm: FakeLLM) -> FakeLLM:
    llm.answers["_Verdict"] = site_verdict
    return llm


@pytest.fixture
def settings(settings: Settings, tmp_path: Path) -> Settings:
    """The shared settings, with the site descriptions and the log inbox in a temp folder."""
    sites = tmp_path / "site_descriptions.json"
    sites.write_text(json.dumps(SITES), encoding="utf-8")
    return settings.model_copy(
        update={"site_descriptions_path": sites, "log_inbox_dir": tmp_path / "inbox"}
    )


@pytest.fixture
async def inventory(deps: Deps) -> AsyncIterator[InventoryService]:
    """A freshly loaded inventory, with the demo organisation's directory in place."""
    async with deps.db.session() as session:
        await session.execute(
            text("TRUNCATE tool_usage, log_ingestions, tools, policy_versions RESTART IDENTITY")
        )
    await deps.directory.replace(
        "seeded",
        DirectoryImport(
            users=[
                DirectoryUserIn(user_id="m.ioannou", display_name="Maria Ioannou", team="Legal"),
                DirectoryUserIn(
                    user_id="g.nikolaou", display_name="Giorgos Nikolaou", team="Legal"
                ),
            ],
            networks=[
                NetworkIn(cidr="10.20.1.0/24", team="Sales"),
                NetworkIn(cidr="10.20.4.0/24", team="Engineering"),
            ],
        ),
    )
    await deps.directory.reload()
    service = await build(deps)
    yield service
    await service.aclose()


@pytest.fixture
async def policy(deps: Deps, inventory: InventoryService) -> PolicyEngine:
    return await build_policy(deps, inventory)


@pytest.fixture
async def api(deps: Deps, inventory: InventoryService) -> AsyncIterator[AsyncClient]:
    """The inventory routes over HTTP, with only the services they use."""
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(keys=deps.keys, db=deps.db, inventory=inventory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway") as client:
        yield client


@pytest.fixture
def signed_in(deps: Deps) -> Callable[[Principal], dict[str, str]]:
    """Request headers that sign a demo user in."""

    def headers(user: Principal) -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_token(user, deps.keys.session, hours=1)}"}

    return headers
