"""The prompt path's inspection with the real detector, vault and policy behind it."""

from typing import Any

import pytest
from mcp import Client

from agent.prompts import system_prompt
from agent.tools import function_name
from gateway.app.core.auth import DEMO_USERS
from gateway.app.core.types import Action
from gateway.app.proxy.inspection import Inspection, Inspector
from gateway.app.proxy.payload import read_responses
from gateway.app.proxy.upstream import COMPANY_ASSISTANT
from gateway.tests.conftest import Api
from mcp_servers.crm.clients import FIXTURE, ClientDirectory
from mcp_servers.crm.server import build_server as build_crm
from mcp_servers.mail.mailbox import Mailbox
from mcp_servers.mail.server import build_server as build_mail
from mcp_servers.web.server import build_server as build_web

pytestmark = pytest.mark.integration

EMPLOYEE = DEMO_USERS[0]
CANARY = "ASPIDA-CANARY-0f3a9c2e4b6d8f1a"
CALL_ID = "call_0f3a9c2e4b6d8f1a3c5e7b9d"


async def agent_tools() -> list[dict[str, Any]]:
    """The function tools the in-house agent offers its model, as the tool servers list them."""
    servers = {
        "crm": build_crm(ClientDirectory(FIXTURE)),
        "mail": build_mail(Mailbox("aspida-demo.example")),
        "web": build_web(),
    }
    tools: list[dict[str, Any]] = []
    for name, server in servers.items():
        async with Client(server) as client:
            tools += [
                {
                    "type": "function",
                    "name": function_name(f"{name}.{tool.name}"),
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                    "strict": False,
                }
                for tool in (await client.list_tools()).tools
            ]
    return tools


async def agent_request() -> dict[str, Any]:
    """A request of the in-house agent in the middle of a turn, built the way it builds one."""
    return {
        "model": "gpt-6-luna",
        "instructions": system_prompt(CANARY),
        "input": [
            {"role": "user", "content": "What is the tax number of Helios Shipping?"},
            {
                "id": "fc_0f3a9c2e4b6d8f1a3c5e7b9d",
                "type": "function_call",
                "status": "completed",
                "call_id": CALL_ID,
                "name": "crm__search_clients",
                "arguments": '{"query": "Helios Shipping"}',
            },
            {
                "type": "function_call_output",
                "call_id": CALL_ID,
                "output": "1 client found:\n- [C-001] <CLIENT_1>, AFM <AFM_1>, <EMAIL_1>",
            },
            {
                "id": "msg_0f3a9c2e4b6d8f1a3c5e7b9d",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "The tax number of <CLIENT_1> is <AFM_1>.",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            },
            {"role": "user", "content": "Email it to accounts@aspida-demo.example please."},
        ],
        "tools": await agent_tools(),
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
    }


async def inspect(api: Api, payload: dict[str, Any], tool: str, conversation: str) -> Inspection:
    services = api.services
    found = await services.inventory.resolve(tool)
    inspector = Inspector(services.detector, services.vault, services.policy)
    return await inspector.inspect(
        principal=EMPLOYEE,
        tool=found,
        conversation_id=conversation,
        vault_id=f"test:{conversation}",
        reading=read_responses(payload, opaque_allowed=True),
    )


async def test_the_in_house_agents_request_is_read_and_not_refused(api: Api) -> None:
    inspection = await inspect(api, await agent_request(), COMPANY_ASSISTANT, "agent-request")
    assert inspection.decision.action in (Action.ALLOW, Action.REDACT)
    assert inspection.error is None
