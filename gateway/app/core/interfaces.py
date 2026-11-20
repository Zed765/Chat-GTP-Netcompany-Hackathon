"""Protocols each gateway module implements. The pipeline depends on these, never on a module."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Protocol

from gateway.app.core.types import (
    ContextualDetection,
    Finding,
    FoundItem,
    InjectionProtection,
    InjectionVerdict,
    LocalDetection,
    MaskResult,
    PlaceholderInfo,
    PolicyContext,
    PolicyDecision,
    RehydrationReport,
    ToolRef,
    Trust,
)


class Detector(Protocol):
    async def detect_local(self, text: str) -> LocalDetection:
        """Normalise, then run T0 and T1. Never calls a model."""
        ...

    async def detect_contextual(
        self,
        masked_text: str,
        *,
        local: LocalDetection,
        force_t3: bool = False,
        use_model: bool = True,
    ) -> ContextualDetection:
        """Run T2, and T3 when T0 to T2 are inconclusive or `force_t3` is set. With
        `use_model=False` it stops at T2."""
        ...

    async def detect_contextual_many(
        self, masked_texts: Sequence[str], *, use_model: bool = True
    ) -> list[ContextualDetection]:
        """`detect_contextual` for many texts at once, with one embedding request for all."""
        ...


class Rehydrator(Protocol):
    """Restores placeholders in a response that arrives in arbitrary chunks."""

    def feed(self, chunk: str) -> str: ...

    def flush(self) -> str: ...

    def report(self) -> RehydrationReport: ...


class Vault(Protocol):
    async def mask(
        self, conversation_id: str, text: str, findings: Sequence[Finding]
    ) -> MaskResult:
        """Replace each maskable finding with a placeholder that is stable for the conversation."""
        ...

    async def rehydrator(self, conversation_id: str, sent: Collection[str]) -> Rehydrator: ...

    async def resolve(self, conversation_id: str, text: str) -> tuple[str, RehydrationReport]:
        """Restore every placeholder in a complete text."""
        ...

    async def describe(self, conversation_id: str) -> list[PlaceholderInfo]:
        """Placeholders held for a conversation, without their values."""
        ...

    async def end(self, conversation_id: str) -> None: ...


class PolicyService(Protocol):
    @property
    def version(self) -> int: ...

    @property
    def injection_protection(self) -> InjectionProtection: ...

    async def decide(self, ctx: PolicyContext, found: Sequence[FoundItem]) -> PolicyDecision: ...


class Inventory(Protocol):
    async def resolve(self, tool: str) -> ToolRef:
        """Look a tool up by slug or domain. An unseen one comes back as `unknown`."""
        ...

    async def approved_alternatives(self, category: str | None) -> list[ToolRef]: ...


class InjectionDetector(Protocol):
    async def inspect(
        self, content: str, *, source: Trust, level: InjectionProtection
    ) -> InjectionVerdict: ...
