"""What the agent and the gateway's proxy must agree on, and what each image may import."""

import re
from pathlib import Path

import pytest

from agent import tools
from agent.prompts import system_prompt
from agent.tools import Inspection, function_name, tool_name
from gateway.app.core.types import Action, InjectionVerdict, Trust
from gateway.app.mcp_proxy import schemas

REPO = Path(__file__).resolve().parents[2]
# The agent, tool server and mock-upstream images carry this one gateway module.
SHARED = "gateway.app.core.types"
GATEWAY_IMPORT = re.compile(r"^\s*(?:from|import)\s+(gateway[\w.]*)", re.MULTILINE)


def test_agent_and_gateway_use_the_same_meta_keys() -> None:
    assert tools.CALL_ID_META_KEY == schemas.CALL_ID_META_KEY
    assert tools.CONFIRMED_META_KEY == schemas.CONFIRMED_META_KEY
    assert tools.INSPECTION_META_KEY == schemas.INSPECTION_META_KEY


def test_agent_reads_the_inspection_the_gateway_writes() -> None:
    written = schemas.ToolInspection(
        call_id="call_1",
        tool="web.fetch_page",
        decision=schemas.CallDecision(
            action=Action.REDACT,
            rule="untrusted-destinations-get-placeholders",
            reason="r",
            resolved=False,
        ),
        layers_run=["canary"],
        result=schemas.ResultInspection(
            source=Trust.UNTRUSTED,
            masked_values=3,
            injection=InjectionVerdict(
                flagged=True, confidence=1.0, evidence="<div>", layers_run=("heuristics",)
            ),
            layers_run=["heuristics"],
            tainted=True,
            taint_source="web.fetch_page",
        ),
    )
    read = Inspection.model_validate(written.model_dump(mode="json"))
    assert read.decision.model_dump() == written.decision.model_dump()
    assert (
        read.result and written.result and read.result.model_dump() == written.result.model_dump()
    )


def test_tool_names_survive_the_trip_through_function_names() -> None:
    assert function_name("crm.search_clients") == "crm__search_clients"
    assert tool_name("crm__search_clients") == "crm.search_clients"
    assert re.fullmatch(r"[A-Za-z0-9_-]+", function_name("mail.send_email"))


def test_system_prompt_carries_the_canary() -> None:
    assert "ASPIDA-CANARY-abc" in system_prompt("ASPIDA-CANARY-abc")


@pytest.mark.parametrize("package", ["agent", "mcp_servers", "mock_upstream"])
def test_image_imports_nothing_from_the_gateway_but_the_shared_types(package: str) -> None:
    sources = [
        path
        for path in (REPO / package).rglob("*.py")
        if "tests" not in path.relative_to(REPO).parts
    ]
    imported = {
        name for path in sources for name in GATEWAY_IMPORT.findall(path.read_text("utf-8"))
    }
    assert sources and imported <= {SHARED}
