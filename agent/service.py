"""Sessions and turns of the demo agent. The gateway decides who may use a session and
holds its taint and canary; the agent keeps the conversation and the trace in memory."""

import logging
from collections.abc import AsyncIterator, Callable

import httpx2
from fastapi import HTTPException, status
from openai import APIStatusError

from agent.config import Settings
from agent.gateway import Gateway, GatewaySession
from agent.loop import confirmation_turn, user_turn
from agent.model import GatewayModel, Model, ModelError
from agent.schemas import AgentEvent, AgentSession, DoneEvent, ErrorEvent
from agent.sessions import Session, SessionStore
from agent.tools import ToolBox

log = logging.getLogger("agent")

Work = Callable[[Model, ToolBox], AsyncIterator[AgentEvent]]


def _explain(error: BaseException) -> str:
    """A message for the user. Only the gateway's own refusal text is passed on."""
    while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        error = error.exceptions[0]
    if isinstance(error, APIStatusError) and isinstance(error.body, dict):
        message = error.body.get("message")
        if isinstance(message, str):
            return message
    if isinstance(error, ModelError):
        return str(error)
    return f"The assistant could not finish this request ({type(error).__name__})."


def _refused(error: httpx2.HTTPError) -> HTTPException:
    """The gateway's answer to a session request, as the agent's own answer."""
    code = error.response.status_code if isinstance(error, httpx2.HTTPStatusError) else None
    if code == status.HTTP_401_UNAUTHORIZED:
        return HTTPException(code, "Sign in first")
    if code == status.HTTP_404_NOT_FOUND:
        return HTTPException(code, "No such agent session")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "The gateway did not answer")


class AgentService:
    def __init__(self, settings: Settings, gateway: Gateway) -> None:
        self._settings = settings
        self._gateway = gateway
        self._sessions = SessionStore()

    @staticmethod
    def _view(session: Session, state: GatewaySession) -> AgentSession:
        session.tainted, session.taint_source = state.tainted, state.taint_source
        return AgentSession(
            session_id=session.session_id,
            protection=state.protection,
            tainted=state.tainted,
            taint_source=state.taint_source,
            messages=session.messages,
            trace=session.trace,
            request_of_call=session.request_of_call,
        )

    async def open(self, token: str, session_id: str) -> tuple[Session, GatewaySession]:
        """The session, once the gateway confirms it belongs to the caller."""
        try:
            state = await self._gateway.session(token, session_id)
        except httpx2.HTTPError as error:
            raise _refused(error) from error
        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such agent session")
        return session, state

    async def create(self, token: str) -> AgentSession:
        try:
            state = await self._gateway.start_session(token)
        except httpx2.HTTPError as error:
            raise _refused(error) from error
        assert state.canary is not None
        session = Session(state.session_id, state.canary)
        self._sessions.add(session)
        return self._view(session, state)

    async def view(self, token: str, session_id: str) -> AgentSession:
        return self._view(*await self.open(token, session_id))

    async def end(self, token: str, session_id: str) -> None:
        await self.open(token, session_id)
        try:
            await self._gateway.end_session(token, session_id)
        except httpx2.HTTPError as error:
            raise _refused(error) from error
        self._sessions.remove(session_id)

    def message(
        self, token: str, session: Session, state: GatewaySession, content: str
    ) -> AsyncIterator[AgentEvent]:
        def work(model: Model, tools: ToolBox) -> AsyncIterator[AgentEvent]:
            return user_turn(session, content, model, tools, max_steps=self._settings.max_steps)

        return self._turn(token, session, state.live_model, work)

    def confirm(
        self, token: str, session: Session, state: GatewaySession, call_id: str, approve: bool
    ) -> AsyncIterator[AgentEvent]:
        def work(model: Model, tools: ToolBox) -> AsyncIterator[AgentEvent]:
            steps = self._settings.max_steps
            return confirmation_turn(session, call_id, approve, model, tools, max_steps=steps)

        return self._turn(token, session, state.live_model, work)

    async def _turn(
        self, token: str, session: Session, model_id: str, work: Work
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn with fresh connections to the gateway. Always ends with `done`."""
        async with session.busy:
            try:
                async with (
                    self._gateway.model_client(token, session.session_id) as client,
                    self._gateway.tools(token, session.session_id) as tools,
                ):
                    async for event in work(GatewayModel(client, model_id), tools):
                        yield event
            except Exception as error:
                # Named by type only: the error text can quote the conversation.
                log.warning("turn failed: %s", type(error).__name__)
                yield ErrorEvent(message=_explain(error))
            yield DoneEvent(tainted=session.tainted, taint_source=session.taint_source)
