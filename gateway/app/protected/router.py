from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from gateway.app.core.auth import Admin
from gateway.app.core.services import Svc
from gateway.app.core.types import RowSource, Store, Tier
from gateway.app.protected.assist import assist
from gateway.app.protected.errors import ProtectedDataError, TooLargeError
from gateway.app.protected.extract import MAX_DOCUMENT_BYTES
from gateway.app.protected.imports import parse_term_file
from gateway.app.protected.preview import mask_preview
from gateway.app.protected.schemas import (
    AssistRequest,
    AssistResult,
    DocumentOut,
    DocumentUploadResult,
    EnabledBody,
    ImportResult,
    ImportSource,
    PatternIn,
    PatternOut,
    ProtectedSummary,
    RemoveDemoResult,
    TermDraft,
    TermOut,
    TermPage,
    TestCategory,
    TestFinding,
    TestRequest,
    TestResult,
)

router = APIRouter(prefix="/api/protected", tags=["protected data"])

MAX_TERM_FILE_BYTES = 2 * 1024 * 1024
MAX_PAGE = 500


def api_errors[**P, R](route: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Answer a store's refusal with its HTTP status and its plain message."""

    @wraps(route)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await route(*args, **kwargs)
        except ProtectedDataError as refusal:
            raise HTTPException(refusal.status, str(refusal)) from refusal

    return wrapped


async def _read(file: UploadFile, limit: int) -> bytes:
    """The upload, held in memory only. One byte over the limit is enough to refuse it."""
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise TooLargeError(f"The file is larger than {limit // (1024 * 1024)} MB")
    return content


@router.get("/summary")
async def summary(svc: Svc, _: Admin) -> ProtectedSummary:
    return svc.protected.summary()


@router.get("/terms")
async def list_terms(
    svc: Svc,
    _: Admin,
    source: RowSource | None = None,
    group: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> TermPage:
    return svc.protected.list_terms(
        source=source,
        group=group,
        query=q,
        offset=max(0, offset),
        limit=min(max(1, limit), MAX_PAGE),
    )


@router.post("/terms")
@api_errors
async def import_terms(
    body: list[TermDraft], svc: Svc, _: Admin, source: ImportSource = "uploaded"
) -> ImportResult:
    """Import the valid rows; the others come back in `errors` with their row number."""
    rows = [row.model_dump() for row in body]
    return await svc.protected.import_terms(rows, RowSource(source))


@router.post("/terms/upload")
@api_errors
async def upload_terms(svc: Svc, _: Admin, file: Annotated[UploadFile, File()]) -> ImportResult:
    """A CSV or JSON file with `term` and optional `aliases` and `data_type`."""
    rows = parse_term_file(file.filename or "", await _read(file, MAX_TERM_FILE_BYTES))
    return await svc.protected.import_terms(rows, RowSource.UPLOADED)


@router.post("/terms/sync")
@api_errors
async def sync_terms(svc: Svc, _: Admin) -> ImportResult:
    """Pull client names from the CRM through the `TermSource` connector."""
    return await svc.protected.sync_terms()


@router.patch("/terms/{term_id}")
@api_errors
async def set_term_enabled(term_id: UUID, body: EnabledBody, svc: Svc, _: Admin) -> TermOut:
    await svc.protected.set_enabled(Store.TERMS, term_id, body.enabled)
    return svc.protected.term(term_id)


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
@api_errors
async def delete_term(term_id: UUID, svc: Svc, _: Admin) -> None:
    await svc.protected.delete(Store.TERMS, term_id)


@router.patch("/groups/{store}/{group}")
@api_errors
async def set_group_enabled(
    store: Store, group: str, body: EnabledBody, svc: Svc, _: Admin
) -> None:
    """Switch a whole default group on or off."""
    await svc.protected.set_group_enabled(store, group, body.enabled)


@router.get("/documents")
async def list_documents(svc: Svc, _: Admin, source: RowSource | None = None) -> list[DocumentOut]:
    return svc.protected.list_documents(source)


@router.post("/documents")
@api_errors
async def upload_document(
    svc: Svc,
    _: Admin,
    file: Annotated[UploadFile, File()],
    label: Annotated[str, Form(min_length=2, max_length=200)],
    category: Annotated[str, Form()],
    source: Annotated[ImportSource, Form()] = "uploaded",
) -> DocumentUploadResult:
    """Fingerprint a document in memory. Its text is never written anywhere."""
    return await svc.protected.add_document(
        filename=file.filename or "",
        content=await _read(file, MAX_DOCUMENT_BYTES),
        label=label,
        category=category,
        source=RowSource(source),
    )


@router.patch("/documents/{document_id}")
@api_errors
async def set_document_enabled(
    document_id: UUID, body: EnabledBody, svc: Svc, _: Admin
) -> DocumentOut:
    await svc.protected.set_enabled(Store.FINGERPRINTS, document_id, body.enabled)
    return svc.protected.document(document_id)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
@api_errors
async def delete_document(document_id: UUID, svc: Svc, _: Admin) -> None:
    await svc.protected.delete(Store.FINGERPRINTS, document_id)


@router.get("/patterns")
async def list_patterns(svc: Svc, _: Admin, source: RowSource | None = None) -> list[PatternOut]:
    return svc.protected.list_patterns(source)


@router.post("/patterns")
@api_errors
async def add_pattern(
    body: PatternIn, svc: Svc, _: Admin, source: ImportSource = "uploaded"
) -> PatternOut:
    """Add a custom pattern. Anything RE2 does not accept is refused with the reason."""
    return await svc.protected.add_pattern(body, RowSource(source))


@router.patch("/patterns/{pattern_id}")
@api_errors
async def set_pattern_enabled(
    pattern_id: UUID, body: EnabledBody, svc: Svc, _: Admin
) -> PatternOut:
    await svc.protected.set_enabled(Store.PATTERNS, pattern_id, body.enabled)
    return svc.protected.pattern(pattern_id)


@router.delete("/patterns/{pattern_id}", status_code=status.HTTP_204_NO_CONTENT)
@api_errors
async def delete_pattern(pattern_id: UUID, svc: Svc, _: Admin) -> None:
    await svc.protected.delete(Store.PATTERNS, pattern_id)


@router.post("/patterns/assist")
async def assisted_pattern(body: AssistRequest, svc: Svc, _: Admin) -> AssistResult:
    """Add a pattern from a plain-language description of a format. The model proposes; its
    expression is checked, and tried on examples and on ordinary text, before it is kept."""
    return await assist(body.request, body.previous, llm=svc.llm, protected=svc.protected)


@router.post("/test")
async def test_prompt(body: TestRequest, svc: Svc, _: Admin) -> TestResult:
    """Run detection on a prompt without forwarding or storing it."""
    local = await svc.detector.detect_local(body.text)
    masked_text, placeholders = mask_preview(body.text, local.findings)
    contextual = await svc.detector.detect_contextual(masked_text, local=local)
    return TestResult(
        masked_text=masked_text,
        findings=[
            TestFinding(
                data_type=finding.data_type,
                start=finding.start,
                end=finding.end,
                placeholder=placeholder,
                tier=finding.tier,
                score=finding.score,
                recogniser=finding.recogniser,
                encoded=finding.encoded,
                masked=placeholder is not None,
                store=finding.match.store if finding.match else None,
                source=finding.match.source if finding.match else None,
                match_label=finding.match.label if finding.match else None,
            )
            for finding, placeholder in zip(local.findings, placeholders, strict=True)
        ],
        categories=[
            TestCategory(
                category=found.category,
                tier=found.tier,
                score=found.score,
                conclusive=found.conclusive,
                evidence=found.evidence,
                store=found.match.store if found.match else None,
                source=found.match.source if found.match else None,
                match_label=found.match.label if found.match else None,
            )
            for found in contextual.categories
        ],
        tiers_run=[Tier.T0, Tier.T1, *contextual.tiers_run],
        timings_ms={
            tier.value: round(elapsed, 2)
            for tier, elapsed in {**local.timings_ms, **contextual.timings_ms}.items()
        },
        notes=[*local.notes, *([contextual.error] if contextual.error else [])],
    )


@router.post("/demo-data/remove")
@api_errors
async def remove_demo_data(svc: Svc, _: Admin) -> RemoveDemoResult:
    return await svc.protected.remove_demo_data()
