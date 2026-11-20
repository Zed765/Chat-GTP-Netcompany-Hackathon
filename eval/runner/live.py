"""Builds the `Toolkit` from the gateway's real services, in process."""

import inspect
from collections.abc import Sequence
from contextlib import AsyncExitStack
from typing import cast

from eval.runner.harness import Detector, Layers, Notebook, Toolkit
from gateway.app.config import Settings
from gateway.app.core.interfaces import InjectionDetector
from gateway.app.core.services import Services, build_services
from gateway.app.core.types import InjectionProtection, InjectionVerdict, RowSource, Trust


async def _default_pack_only(services: Services) -> Detector | None:
    """The detector limited to the default pack, if this build can limit one."""
    scoped = getattr(services.detector, "scoped", None)
    if scoped is None:
        return None
    limited = scoped([RowSource.DEFAULT])
    return cast(Detector, await limited if inspect.isawaitable(limited) else limited)


class _Layer1Only:
    """The injection detector as it answers for a trusted source, which it never sends to
    the model: layer 1 on its own."""

    def __init__(self, detector: InjectionDetector) -> None:
        self._detector = detector

    async def inspect(
        self, content: str, *, source: Trust, level: InjectionProtection
    ) -> InjectionVerdict:
        return await self._detector.inspect(content, source=Trust.TRUSTED, level=level)


async def build_toolkit(
    settings: Settings, stack: AsyncExitStack, layers: Sequence[Layers], notebook: Notebook
) -> Toolkit:
    services = await build_services(settings, stack)
    detectors: dict[Layers, Detector] = {}
    if "default" in layers:
        limited = await _default_pack_only(services)
        if limited is None:
            notebook.skipped.append(
                "default-pack-only metrics: this detector cannot be limited to one layer"
            )
        else:
            detectors["default"] = limited
    if "default+demo" in layers:
        if settings.seed_demo_data:
            detectors["default+demo"] = cast(Detector, services.detector)
        else:
            notebook.skipped.append(
                "default+demo metrics: the demo organisation is not loaded (SEED_DEMO_DATA=false)"
            )
    return Toolkit(
        detectors=detectors,
        vault=services.vault,
        injection={
            "layer 1": _Layer1Only(services.injection),
            "layer 1 + layer 2": services.injection,
        },
        policy=services.policy,
        models={
            "inline": settings.model_inline,
            "offline": settings.model_offline,
            "embedding": services.llm.embedder_id,
        },
        embedder_id=services.llm.embedder_id,
        normalisation_switch="normalise"
        in inspect.signature(services.detector.detect_local).parameters,
    )
