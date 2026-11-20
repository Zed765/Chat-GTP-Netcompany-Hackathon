"""Where a request for an AI tool is forwarded, and with which credentials."""

from dataclasses import dataclass

from fastapi import HTTPException, status

from gateway.app.config import Settings
from gateway.app.core.types import ToolRef
from gateway.app.llm.client import OPENAI_BASE_URL

COMPANY_ASSISTANT = "company-assistant"


@dataclass(frozen=True)
class Upstream:
    base_url: str
    headers: dict[str, str]
    is_company_model: bool


def resolve_upstream(tool: ToolRef, settings: Settings) -> Upstream:
    """The company's own assistant goes to OpenAI with the gateway's key. Any other tool
    goes to the endpoint the inventory holds."""
    if tool.slug == COMPANY_ASSISTANT:
        return Upstream(
            settings.openai_base_url or OPENAI_BASE_URL,
            {"Authorization": f"Bearer {settings.api_key}"},
            True,
        )
    if tool.upstream_url is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{tool.name} has no API endpoint in the inventory, so prompts cannot be sent to it",
        )
    return Upstream(tool.upstream_url, {}, False)
