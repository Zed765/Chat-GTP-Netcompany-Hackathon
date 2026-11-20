import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from gateway.app.core.deps import Deps
from gateway.app.core.types import (
    Channel,
    DataType,
    FoundItem,
    InjectionProtection,
    PolicyContext,
    PolicyDecision,
    Principal,
    ToolRef,
)
from gateway.app.discovery import InventoryService
from gateway.app.policy import store
from gateway.app.policy.document import Checked, PolicyDocument, PolicyInvalidError, check
from gateway.app.policy.edit import with_injection_protection
from gateway.app.policy.evaluate import Outcome, evaluate, is_milder_at, with_tool_status
from gateway.app.policy.explain import explain
from gateway.app.policy.models import PolicyVersion

DEFAULT_POLICY_FILE = "default.yaml"


@dataclass(frozen=True)
class _Loaded:
    version: int
    document: PolicyDocument


class PolicyEngine:
    """Implements `core.interfaces.PolicyService`."""

    def __init__(self, deps: Deps, inventory: InventoryService) -> None:
        self._deps = deps
        self._inventory = inventory
        self._loaded: _Loaded | None = None
        self.known_data_types: Callable[[], frozenset[str]] = lambda: DataType.BUILT_IN

    @property
    def version(self) -> int:
        return self._current.version

    @property
    def injection_protection(self) -> InjectionProtection:
        return self._current.document.injection_protection

    @property
    def document(self) -> PolicyDocument:
        return self._current.document

    async def reload(self) -> None:
        """Load the active policy, saving `policies/default.yaml` as version 1 if none exists."""
        async with self._deps.db.session() as session:
            row = await store.active(session)
            if row is None:
                row = await store.active_or_first(session, await self._default_policy())
        # A data type that has since been removed only stops its rule from matching.
        document = (await self.check(row.yaml)).document
        if document is None:
            raise RuntimeError(f"Saved policy version {row.version} cannot be read")
        self._loaded = _Loaded(row.version, document)

    async def decide(self, ctx: PolicyContext, found: Sequence[FoundItem]) -> PolicyDecision:
        loaded = self._current
        tool = None
        if ctx.channel is Channel.PROMPT and ctx.tool:
            tool = await self._inventory.resolve(ctx.tool)
        ctx = with_tool_status(ctx, tool.status if tool else None)
        outcome = evaluate(loaded.document, ctx)
        alternatives = await self._alternatives(loaded.document, ctx, outcome, tool)
        return PolicyDecision(
            action=outcome.action,
            rule=outcome.rule,
            policy_version=loaded.version,
            matched_types=outcome.matched_types,
            explanation=explain(ctx, found, outcome, tool, alternatives),
        )

    async def check(self, yaml_text: str) -> Checked:
        return await asyncio.to_thread(check, yaml_text, self.known_data_types())

    async def activate(
        self, yaml_text: str, actor: Principal, note: str | None = None
    ) -> PolicyVersion:
        """Validate, save as a new version, and reload every worker.

        Text identical to the active policy changes nothing and returns the active version.
        """
        checked = await self.check(yaml_text)
        if checked.document is None or not checked.valid:
            raise PolicyInvalidError(checked.issues)
        async with self._deps.db.session() as session:
            current = await store.active(session)
            if current is not None and current.yaml == yaml_text:
                return current
            row = await store.save_as_active(
                session, yaml_text, author=actor.display_name, note=note
            )
        await self._deps.bus.publish("policy")
        return row

    async def set_injection_protection(
        self, level: InjectionProtection, actor: Principal
    ) -> PolicyVersion:
        """Save a version that differs from the active one only in this setting."""
        async with self._deps.db.session() as session:
            row = await store.active(session)
        document = (await self.check(row.yaml)).document if row else None
        if row is None or document is None:
            raise RuntimeError("There is no readable active policy")
        if document.injection_protection is level:
            return row
        edited = await asyncio.to_thread(with_injection_protection, row.yaml, document, level)
        return await self.activate(edited, actor, f"Injection protection set to {level.value}")

    @property
    def _current(self) -> _Loaded:
        if self._loaded is None:
            raise RuntimeError("The policy is not loaded yet; `build` loads it")
        return self._loaded

    async def _default_policy(self) -> str:
        path = self._deps.settings.policies_dir / DEFAULT_POLICY_FILE
        text = path.read_text(encoding="utf-8")
        checked = await self.check(text)
        if not checked.valid:
            problems = "; ".join(f"{issue.path}: {issue.message}" for issue in checked.issues)
            raise RuntimeError(f"{path} is not a valid policy: {problems}")
        return text

    async def _alternatives(
        self, policy: PolicyDocument, ctx: PolicyContext, outcome: Outcome, tool: ToolRef | None
    ) -> list[ToolRef]:
        """Approved tools where the same request would get a milder decision."""
        if ctx.channel is not Channel.PROMPT or not outcome.suggest_alternative:
            return []
        candidates = await self._inventory.approved_alternatives(tool.category if tool else None)
        return [
            other
            for other in candidates
            if (tool is None or other.slug != tool.slug)
            and is_milder_at(policy, ctx, other, outcome.action)
        ]


async def build(deps: Deps, inventory: InventoryService) -> PolicyEngine:
    engine = PolicyEngine(deps, inventory)
    await engine.reload()
    deps.bus.subscribe("policy", engine.reload)
    return engine
