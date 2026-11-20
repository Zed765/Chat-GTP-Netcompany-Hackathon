import gc
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from gateway.app import demo
from gateway.app.analyst.router import router as analyst_router
from gateway.app.config import Settings, get_settings
from gateway.app.core.services import build_services
from gateway.app.discovery.router import router as discovery_router
from gateway.app.llm.client import LLM
from gateway.app.mcp_proxy.router import router as mcp_router
from gateway.app.policy.router import router as policy_router
from gateway.app.privacy.router import router as privacy_router
from gateway.app.protected.router import router as protected_router
from gateway.app.proxy.router import router as proxy_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    """`llm` stands in for the OpenAI client, so that tests call no model."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app.state.services = await build_services(settings or get_settings(), stack, llm)
            # A full collection would walk every object of the loaded language models
            # and hold a request for 0.1 to 0.2 s; frozen, it takes a few milliseconds.
            gc.collect()
            gc.freeze()
            try:
                yield
            finally:
                gc.unfreeze()

    app = FastAPI(
        title="A.S.P.I.D.A. gateway",
        summary="AI Security Proxy for Injection Defense & Anonymization",
        version="0.1.0",
        lifespan=lifespan,
    )
    for router in (
        demo.router,
        proxy_router,
        discovery_router,
        protected_router,
        policy_router,
        analyst_router,
        privacy_router,
        mcp_router,
    ):
        app.include_router(router)
    return app


app = create_app()
