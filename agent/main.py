import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast

import httpx2
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent.config import Settings
from agent.gateway import Gateway
from agent.schemas import AgentEvent, AgentSession, ConfirmIn, ErrorEvent, MessageIn
from agent.service import AgentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")

_EVENT_STREAM: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Server-sent events. Each `data:` line is one `AgentEvent` as JSON.",
        "content": {"text/event-stream": {}},
        "model": AgentEvent,
    },
    409: {"description": "The assistant is still working on this session's previous turn."},
}
_bearer = HTTPBearer(auto_error=False)


def _token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> str:
    """The signed-in user's session token. The agent forwards it; the gateway verifies it."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    return credentials.credentials


def _service(request: Request) -> AgentService:
    return cast(AgentService, request.app.state.service)


Token = Annotated[str, Depends(_token)]
Service = Annotated[AgentService, Depends(_service)]


def _server_sent(events: AsyncIterator[AgentEvent]) -> StreamingResponse:
    """Stream a turn. It runs in a task of its own, so that the connections it opens are
    closed by the task that opened them even if the browser goes away."""
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    async def run_turn() -> None:
        try:
            async for event in events:
                queue.put_nowait(event)
        except Exception as error:
            log.warning("turn ended early: %s", type(error).__name__)
            queue.put_nowait(ErrorEvent(message="The assistant stopped unexpectedly."))
        finally:
            queue.put_nowait(None)

    async def body() -> AsyncIterator[str]:
        turn = asyncio.create_task(run_turn())
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {event.model_dump_json()}\n\n"
        finally:
            turn.cancel()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(body(), media_type="text/event-stream", headers=headers)


def create_app(transport: httpx2.AsyncBaseTransport | None = None) -> FastAPI:
    """`transport` replaces the network path to the gateway, for running in one process."""
    settings = Settings()
    app = FastAPI(title="A.S.P.I.D.A. demo agent", version="0.1.0")
    app.state.service = AgentService(settings, Gateway(settings, transport))

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(token: Token, service: Service) -> AgentSession:
        return await service.create(token)

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str, token: Token, service: Service) -> AgentSession:
        return await service.view(token, session_id)

    @app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def end_session(session_id: str, token: Token, service: Service) -> None:
        """Forget the conversation here and its vault entries, taint and canary in the gateway."""
        await service.end(token, session_id)

    @app.post("/sessions/{session_id}/messages", responses=_EVENT_STREAM)
    async def send_message(
        session_id: str, body: MessageIn, token: Token, service: Service
    ) -> StreamingResponse:
        session, state = await service.open(token, session_id)
        if session.busy.locked():
            raise HTTPException(status.HTTP_409_CONFLICT, "The assistant is still working")
        return _server_sent(service.message(token, session, state, body.content))

    @app.post("/sessions/{session_id}/confirmations/{call_id}", responses=_EVENT_STREAM)
    async def confirm_call(
        session_id: str, call_id: str, body: ConfirmIn, token: Token, service: Service
    ) -> StreamingResponse:
        """Approve or reject a side-effect call that the policy held for confirmation."""
        session, state = await service.open(token, session_id)
        if session.busy.locked():
            raise HTTPException(status.HTTP_409_CONFLICT, "The assistant is still working")
        if call_id not in session.held:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such call is waiting")
        return _server_sent(service.confirm(token, session, state, call_id, body.approve))

    return app


app = create_app()
