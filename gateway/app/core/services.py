from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis

from gateway.app import detect, discovery, mcp_proxy, policy, protected, vault
from gateway.app.config import Settings
from gateway.app.core.deps import Deps
from gateway.app.core.keys import Keys, load_keys
from gateway.app.core.reload import ReloadBus
from gateway.app.db.readonly import readonly_database
from gateway.app.db.session import Database
from gateway.app.events.writer import EventWriter
from gateway.app.llm.client import LLM
from gateway.app.mcp_proxy.trust import RELOAD_TOPIC as AGENT_TRUST_TOPIC
from gateway.app.mcp_proxy.trust import AgentTrust, AgentTrustStore
from gateway.app.privacy.directory import Directory
from gateway.app.privacy.identity import Identities
from gateway.app.privacy.retention import Retention
from gateway.app.privacy.store import STORE_SNIPPETS, SettingsStore

UPSTREAM_TIMEOUT_S = 120.0
CONNECT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Services:
    settings: Settings
    keys: Keys
    db: Database
    readonly_db: Database
    redis: Redis
    http: httpx.AsyncClient
    bus: ReloadBus
    llm: LLM
    directory: Directory
    store: SettingsStore
    retention: Retention
    agent_trust: AgentTrustStore
    identities: Identities
    events: EventWriter
    protected: protected.ProtectedData
    detector: detect.DetectionService
    vault: vault.VaultService
    inventory: discovery.InventoryService
    policy: policy.PolicyEngine
    injection: mcp_proxy.InjectionService


async def build_services(
    settings: Settings, stack: AsyncExitStack, llm: LLM | None = None
) -> Services:
    """`llm` stands in for the OpenAI client, so that tests call no model."""
    keys = load_keys(settings.keys_dir)
    db = Database(settings.database_url)
    stack.push_async_callback(db.dispose)
    configured = settings.readonly_db_password
    readonly_db = await readonly_database(
        db,
        settings.database_url,
        configured.get_secret_value() if configured else keys.readonly_db.hex(),
    )
    stack.push_async_callback(readonly_db.dispose)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    stack.push_async_callback(redis.aclose)
    http = httpx.AsyncClient(timeout=httpx.Timeout(UPSTREAM_TIMEOUT_S, connect=CONNECT_TIMEOUT_S))
    stack.push_async_callback(http.aclose)
    bus = ReloadBus(redis)
    await bus.start()
    stack.push_async_callback(bus.stop)

    directory = Directory(db, keys.pseudonym)
    await directory.reload()
    bus.subscribe("directory", directory.reload)

    deps = Deps(
        settings=settings,
        keys=keys,
        db=db,
        redis=redis,
        bus=bus,
        llm=llm or LLM(settings),
        directory=directory,
    )
    store = SettingsStore(db)
    retention = Retention(db, store, settings.retention_days)
    await retention.start()
    stack.push_async_callback(retention.stop)
    events = EventWriter(db, keys.pseudonym)

    async def reload_privacy() -> None:
        events.store_snippets = bool(await store.get(STORE_SNIPPETS, True))

    await reload_privacy()
    bus.subscribe("privacy", reload_privacy)
    agent_trust = AgentTrustStore(store, AgentTrust.configured(settings))
    await agent_trust.reload()
    bus.subscribe(AGENT_TRUST_TOPIC, agent_trust.reload)
    protected_data = await protected.build(deps)
    inventory = await discovery.build(deps)
    stack.push_async_callback(inventory.aclose)
    policy_engine = await policy.build(deps, inventory)
    # A data type a company adds to its stores becomes valid in the policy's `data` lists.
    policy_engine.known_data_types = protected_data.data_types
    return Services(
        settings=settings,
        keys=keys,
        db=db,
        readonly_db=readonly_db,
        redis=redis,
        http=http,
        bus=bus,
        llm=deps.llm,
        directory=directory,
        store=store,
        retention=retention,
        agent_trust=agent_trust,
        identities=Identities(db, directory),
        events=events,
        protected=protected_data,
        detector=await detect.build(deps, protected_data),
        vault=await vault.build(deps),
        inventory=inventory,
        policy=policy_engine,
        injection=await mcp_proxy.build(deps),
    )


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


Svc = Annotated[Services, Depends(get_services)]
