from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from gateway.app.core.auth import Admin, CurrentPrincipal
from gateway.app.core.services import Services, Svc
from gateway.app.policy import store
from gateway.app.policy.document import Checked, PolicyInvalidError
from gateway.app.policy.draft import Vocabulary, draft_rule
from gateway.app.policy.models import PolicyVersion
from gateway.app.policy.replay import replay as replay_events
from gateway.app.policy.schemas import (
    ActivateRequest,
    DraftRequest,
    DraftResult,
    InjectionProtectionBody,
    PolicyOut,
    PolicyText,
    PolicyVersionSummary,
    ReplayRequest,
    ReplayResult,
    ValidateResult,
)

router = APIRouter(prefix="/api/policy", tags=["policy"])

_INVALID: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ValidateResult,
        "description": "The policy is not valid; the body lists the issues",
    }
}


def _summary(row: PolicyVersion) -> PolicyVersionSummary:
    return PolicyVersionSummary(
        version=row.version,
        note=row.note,
        author=row.author,
        created=row.created,
        active=row.active,
    )


async def _out(row: PolicyVersion, services: Services) -> PolicyOut:
    document = (await services.policy.check(row.yaml)).document
    if document is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "This version cannot be read")
    return PolicyOut(
        **_summary(row).model_dump(),
        yaml=row.yaml,
        injection_protection=document.injection_protection,
    )


def _validation(checked: Checked) -> ValidateResult:
    return ValidateResult(valid=checked.valid, issues=list(checked.issues))


def _invalid(result: ValidateResult) -> JSONResponse:
    return JSONResponse(result.model_dump(mode="json"), status.HTTP_400_BAD_REQUEST)


@router.get("")
async def active_policy(services: Svc, _: Admin) -> PolicyOut:
    async with services.db.session() as session:
        row = await store.active(session)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No policy is active")
    return await _out(row, services)


@router.get("/versions")
async def list_versions(services: Svc, _: Admin) -> list[PolicyVersionSummary]:
    async with services.db.session() as session:
        return [_summary(row) for row in await store.newest_first(session)]


@router.get("/versions/{version}")
async def get_version(version: int, services: Svc, _: Admin) -> PolicyOut:
    async with services.db.session() as session:
        row = await store.by_version(session, version)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such policy version")
    return await _out(row, services)


@router.post("/validate")
async def validate(body: PolicyText, services: Svc, _: Admin) -> ValidateResult:
    return _validation(await services.policy.check(body.yaml))


@router.post("/draft")
async def draft_rule_from_text(body: DraftRequest, services: Svc, _: Admin) -> DraftResult:
    """Propose one rule for a plain-language instruction, merged into the given YAML."""
    vocabulary = Vocabulary(
        data_types=services.policy.known_data_types(),
        tools=services.inventory.tools(),
        teams=services.directory.teams(),
    )
    return await draft_rule(body.instruction, body.yaml, llm=services.llm, vocabulary=vocabulary)


@router.post("/replay", response_model=ReplayResult, responses=_INVALID)
async def replay(body: ReplayRequest, services: Svc, _: Admin) -> ReplayResult | JSONResponse:
    """What the draft would have decided on recent events, compared with the active policy."""
    checked = await services.policy.check(body.yaml)
    if checked.document is None or not checked.valid:
        return _invalid(_validation(checked))
    return await replay_events(services.db, services.policy.document, checked.document, body.days)


@router.post("/activate", response_model=PolicyOut, responses=_INVALID)
async def activate(
    body: ActivateRequest, services: Svc, analyst: Admin
) -> PolicyOut | JSONResponse:
    try:
        row = await services.policy.activate(body.yaml, analyst, body.note)
    except PolicyInvalidError as exc:
        return _invalid(ValidateResult(valid=False, issues=list(exc.issues)))
    return await _out(row, services)


@router.get("/injection-protection")
async def get_injection_protection(services: Svc, _: CurrentPrincipal) -> InjectionProtectionBody:
    return InjectionProtectionBody(level=services.policy.injection_protection)


@router.put("/injection-protection")
async def set_injection_protection(
    body: InjectionProtectionBody, services: Svc, analyst: Admin
) -> PolicyOut:
    """Saves a new policy version that differs only in `injection_protection`."""
    row = await services.policy.set_injection_protection(body.level, analyst)
    return await _out(row, services)
