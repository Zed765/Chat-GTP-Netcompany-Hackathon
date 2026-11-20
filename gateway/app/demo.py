"""Demo-only endpoints: sign-in, build facts for the UI, and the attacker's inbox."""

from importlib.metadata import version

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from gateway.app.core.auth import DEMO_USERS, Admin, CurrentPrincipal, issue_token
from gateway.app.core.services import Svc
from gateway.app.core.types import Principal
from gateway.app.privacy.store import SEED_STEPS

router = APIRouter(tags=["demo"])


class Models(BaseModel):
    inline: str
    offline: str
    embedding: str


class Meta(BaseModel):
    product: str
    seed_demo_data: bool
    embedder_id: str
    models: Models
    fastapi_version: str


class LoginRequest(BaseModel):
    user_id: str


class Session(BaseModel):
    token: str
    user: Principal


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/meta")
async def meta(services: Svc) -> Meta:
    settings = services.settings
    return Meta(
        product="A.S.P.I.D.A.",
        seed_demo_data=settings.seed_demo_data,
        embedder_id=services.llm.embedder_id,
        models=Models(
            inline=settings.model_inline,
            offline=settings.model_offline,
            embedding=settings.model_embedding,
        ),
        fastapi_version=version("fastapi"),
    )


@router.get("/api/demo/users")
async def demo_users() -> list[Principal]:
    return list(DEMO_USERS)


@router.post("/api/demo/login")
async def demo_login(body: LoginRequest, services: Svc) -> Session:
    """Demo sign-in: anyone can become any demo user. Replace with single sign-on in production."""
    user = next((user for user in DEMO_USERS if user.user_id == body.user_id), None)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown demo user")
    token = issue_token(user, services.keys.session, services.settings.session_hours)
    return Session(token=token, user=user)


@router.get("/api/me")
async def me(principal: CurrentPrincipal) -> Principal:
    return principal


@router.get("/api/demo/seed-state")
async def seed_state(_: CurrentPrincipal, services: Svc) -> list[str]:
    """The seeding steps that have completed, so the seeder can skip them on a restart."""
    return list(await services.store.get(SEED_STEPS, []))


@router.put("/api/demo/seed-state/{step}", status_code=status.HTTP_204_NO_CONTENT)
async def mark_seed_step(step: str, _: Admin, services: Svc) -> None:
    steps = list(await services.store.get(SEED_STEPS, []))
    if step not in steps:
        await services.store.put(SEED_STEPS, [*steps, step])
