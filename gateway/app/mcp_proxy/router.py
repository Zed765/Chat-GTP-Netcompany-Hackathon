import httpx2
from fastapi import APIRouter, HTTPException, status
from starlette.routing import Route

from gateway.app.core.auth import Admin, CurrentPrincipal
from gateway.app.core.conversation import vault_conversation
from gateway.app.core.services import Services, Svc
from gateway.app.core.types import Principal
from gateway.app.mcp_proxy.schemas import (
    AgentSessionCreated,
    AgentSessionOut,
    AgentSystem,
    AgentTool,
    AgentTrustOut,
    AgentTrustUpdate,
    InboxMessage,
    SeenRequest,
    SeenResult,
)
from gateway.app.mcp_proxy.server import McpEndpoint, Proxy, lifespan
from gateway.app.mcp_proxy.sessions import SessionState
from gateway.app.mcp_proxy.trust import RELOAD_TOPIC, AgentTrust
from gateway.app.mcp_proxy.upstream import server_urls

MCP_PATH = "/mcp"

router = APIRouter(tags=["agent"], lifespan=lifespan)
# The agent's single MCP endpoint (streamable HTTP). Not an API route, so not in OpenAPI.
router.routes.append(Route(MCP_PATH, endpoint=McpEndpoint(), methods=["GET", "POST", "DELETE"]))


def _session_out(state: SessionState, services: Services) -> AgentSessionOut:
    return AgentSessionOut(
        session_id=state.session_id,
        protection=services.policy.injection_protection,
        tainted=state.tainted,
        taint_source=state.taint_source,
        live_model=services.settings.model_inline,
    )


async def _owned_session(session_id: str, principal: Principal, proxy: Proxy) -> SessionState:
    state = await proxy.sessions.get(session_id)
    if state is None or state.owner != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such agent session")
    return state


@router.post("/api/agent/sessions", status_code=status.HTTP_201_CREATED)
async def create_agent_session(
    principal: CurrentPrincipal, proxy: Proxy, services: Svc
) -> AgentSessionCreated:
    """Start an agent session. Its ID scopes the vault, the taint and the canary."""
    state = await proxy.sessions.create(principal.user_id)
    return AgentSessionCreated(**_session_out(state, services).model_dump(), canary=state.canary)


@router.get("/api/agent/sessions/{session_id}")
async def get_agent_session(
    session_id: str, principal: CurrentPrincipal, proxy: Proxy, services: Svc
) -> AgentSessionOut:
    return _session_out(await _owned_session(session_id, principal, proxy), services)


@router.delete("/api/agent/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_agent_session(
    session_id: str, principal: CurrentPrincipal, proxy: Proxy, services: Svc
) -> None:
    """Forget the session and delete its vault entries now instead of waiting for the TTL."""
    await _owned_session(session_id, principal, proxy)
    await services.vault.end(vault_conversation(principal, session_id, services.keys.pseudonym))
    await proxy.sessions.end(session_id)


async def _trust_out(proxy: Proxy, services: Services) -> AgentTrustOut:
    trust = services.agent_trust.current
    catalogue = (await proxy.broker.servers.catalogue()).values()
    return AgentTrustOut(
        systems=[
            AgentSystem(
                server=server,
                trusted=server in trust.servers,
                tools=[
                    AgentTool(
                        name=tool.definition.name,
                        description=tool.definition.description,
                        side_effects=tool.side_effects,
                    )
                    for tool in catalogue
                    if tool.server == server
                ],
            )
            for server in server_urls(services.settings)
        ],
        mail_domains=sorted(trust.mail_domains),
    )


@router.get("/api/agent/trust")
async def get_agent_trust(_: Admin, proxy: Proxy, services: Svc) -> AgentTrustOut:
    """The systems the agent reaches, the tools of each, and how far each is trusted."""
    return await _trust_out(proxy, services)


@router.put("/api/agent/trust")
async def set_agent_trust(
    body: AgentTrustUpdate, _: Admin, proxy: Proxy, services: Svc
) -> AgentTrustOut:
    """Applies from the agent's next tool call."""
    unknown = sorted(set(body.trusted_servers) - set(server_urls(services.settings)))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"No such system: {', '.join(unknown)}"
        )
    trust = AgentTrust(frozenset(body.trusted_servers), frozenset(body.mail_domains))
    await services.agent_trust.save(trust)
    await services.bus.publish(RELOAD_TOPIC)
    return await _trust_out(proxy, services)


@router.post("/api/agent/sessions/{session_id}/as-seen")
async def as_the_agent_saw(
    session_id: str, body: SeenRequest, principal: CurrentPrincipal, proxy: Proxy, services: Svc
) -> SeenResult:
    """The caller's own texts with every value in the session's vault replaced by its
    placeholder: the conversation as the agent's model saw it. Nothing comes back that the
    caller did not send."""
    await _owned_session(session_id, principal, proxy)
    conversation = vault_conversation(principal, session_id, services.keys.pseudonym)
    return SeenResult(texts=await services.vault.as_sent(conversation, body.texts))


async def _mail_server(proxy: Proxy, services: Services, method: str) -> httpx2.Response:
    try:
        response = await proxy.http.request(method, f"{services.settings.mail_url}/attacker-inbox")
        return response.raise_for_status()
    except httpx2.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The mock mail server did not answer"
        ) from exc


@router.get("/api/demo/attacker-inbox")
async def attacker_inbox(_: CurrentPrincipal, proxy: Proxy, services: Svc) -> list[InboxMessage]:
    """Everything outside addresses received from the mock mail server."""
    response = await _mail_server(proxy, services, "GET")
    return [InboxMessage.model_validate(message) for message in response.json()]


@router.delete("/api/demo/attacker-inbox", status_code=status.HTTP_204_NO_CONTENT)
async def clear_attacker_inbox(_: CurrentPrincipal, proxy: Proxy, services: Svc) -> None:
    await _mail_server(proxy, services, "DELETE")
