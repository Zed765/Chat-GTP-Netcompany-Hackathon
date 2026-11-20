import json
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Header, status
from fastapi.responses import Response
from pydantic import TypeAdapter

from gateway.app.core.auth import Admin, CurrentPrincipal
from gateway.app.core.conversation import vault_conversation
from gateway.app.core.services import Services, Svc
from gateway.app.proxy.chat import handle_chat
from gateway.app.proxy.context import ProxyContext
from gateway.app.proxy.ingest import ingest_prompts
from gateway.app.proxy.inspection import Inspector
from gateway.app.proxy.responses import handle_responses
from gateway.app.proxy.schemas import (
    ACKNOWLEDGE_HEADER,
    CONVERSATION_HEADER,
    TOOL_HEADER,
    ChatCompletionEnvelope,
    ChatCompletionRequest,
    Example,
    IngestResult,
    PolicyErrorResponse,
    PromptRecord,
    ResponsesRequest,
)

router = APIRouter(tags=["proxy"])

MAX_INGEST_BATCH = 200
EXAMPLES_FILE = "examples.json"
_examples = TypeAdapter(list[Example])

_POLICY_ANSWERS: dict[int | str, dict[str, object]] = {
    403: {"model": PolicyErrorResponse, "description": "Blocked by policy"},
    409: {"model": PolicyErrorResponse, "description": "Warning that needs acknowledgement"},
}

ToolHeader = Annotated[str | None, Header(alias=TOOL_HEADER)]
ConversationHeader = Annotated[str | None, Header(alias=CONVERSATION_HEADER, max_length=64)]


def _context(services: Services) -> ProxyContext:
    return ProxyContext(
        settings=services.settings,
        pseudonym_key=services.keys.pseudonym,
        inspector=Inspector(services.detector, services.vault, services.policy),
        vault=services.vault,
        inventory=services.inventory,
        events=services.events,
        http=services.http,
    )


@router.post(
    "/v1/chat/completions", response_model=ChatCompletionEnvelope, responses=_POLICY_ANSWERS
)
async def chat_completions(
    body: ChatCompletionRequest,
    principal: CurrentPrincipal,
    services: Svc,
    tool: ToolHeader = None,
    conversation: ConversationHeader = None,
    acknowledged: Annotated[
        str | None,
        Header(
            alias=ACKNOWLEDGE_HEADER,
            description="The `trace_id` of the warning being acknowledged",
        ),
    ] = None,
) -> Response:
    """OpenAI Chat Completions, inspected. Sensitive values are replaced with placeholders
    before the AI tool sees them and restored in its answer."""
    return await handle_chat(
        _context(services),
        principal,
        body,
        tool_name=tool,
        conversation=conversation,
        acknowledged=acknowledged,
    )


@router.post("/v1/responses", response_model=None, responses=_POLICY_ANSWERS)
async def responses(
    body: ResponsesRequest,
    principal: CurrentPrincipal,
    services: Svc,
    tool: ToolHeader = None,
    conversation: ConversationHeader = None,
) -> Response:
    """The OpenAI Responses API, inspected. Assistant text comes back restored;
    function-call arguments keep their placeholders."""
    return await handle_responses(
        _context(services), principal, body, tool_name=tool, conversation=conversation
    )


@router.post("/api/conversations/{conversation_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_conversation(
    conversation_id: str, principal: CurrentPrincipal, services: Svc
) -> None:
    """Delete the conversation's vault entries now instead of waiting for the TTL."""
    await services.vault.end(
        vault_conversation(principal, conversation_id, services.keys.pseudonym)
    )


@router.post("/api/ingest/prompts")
async def ingest(
    body: Annotated[list[PromptRecord], Body(max_length=MAX_INGEST_BATCH)],
    _: Admin,
    services: Svc,
) -> IngestResult:
    """Inspect prompts from an activity log. Each becomes an event; the text is not kept."""
    return await ingest_prompts(
        body,
        detector=services.detector,
        policy=services.policy,
        inventory=services.inventory,
        directory=services.directory,
        events=services.events,
    )


@router.get("/api/examples")
async def examples(
    _: CurrentPrincipal, services: Svc, page: Literal["chat"] | None = None
) -> list[Example]:
    """Ready-made prompts for the "Try an example" buttons."""
    path = services.settings.defaults_dir / EXAMPLES_FILE
    loaded = _examples.validate_python(json.loads(path.read_text())) if path.exists() else []
    return [example for example in loaded if page is None or example.page == page]
