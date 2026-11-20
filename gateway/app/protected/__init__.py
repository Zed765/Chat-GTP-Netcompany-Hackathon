import asyncio

from gateway.app.core.deps import Deps
from gateway.app.detect.ner import shared_ner_engine
from gateway.app.protected.service import TOPIC, ProtectedData

__all__ = ["ProtectedData", "build"]


async def build(deps: Deps) -> ProtectedData:
    store = ProtectedData(deps, ner=await asyncio.to_thread(shared_ner_engine))
    await store.load_default_pack()
    await store.reload()
    deps.bus.subscribe(TOPIC, store.reload)
    await store.refresh_synced_terms()
    return store
