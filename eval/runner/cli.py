"""`python -m eval.runner --out DIR`: computes every metric it can and writes one results file.

It runs inside the gateway container: detection, the vault and injection detection are
called in process, and the leak and rehydration checks go through the running gateway.
"""

import argparse
import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

from eval.runner import metrics, roundtrip
from eval.runner.harness import Layers, Notebook, Toolkit
from eval.runner.live import build_toolkit
from eval.runner.samples import (
    AgentScenario,
    CategorySample,
    DlpSample,
    EvasionSample,
    FingerprintSample,
    InjectionSample,
    load,
    sizes,
)
from eval.schema import EvalResults, LeakResult, RehydrationResult
from gateway.app.config import get_settings

GATEWAY_URL = "http://localhost:8000"
LAYER_CHOICES: dict[str, tuple[Layers, ...]] = {
    "default": ("default",),
    "default+demo": ("default+demo",),
    "both": ("default", "default+demo"),
}
SPLIT = "test (the 30% of each set held out from threshold tuning)"


async def _stack_checks(
    toolkit: Toolkit,
    samples: Sequence[DlpSample],
    notebook: Notebook,
    gateway_url: str,
    upstream_url: str,
) -> tuple[list[RehydrationResult], roundtrip.LeakCheck | None]:
    """The two checks that need the running gateway and the fake AI tools."""
    rehydration: list[RehydrationResult] = []
    leak = None
    async with (
        httpx.AsyncClient(base_url=gateway_url, timeout=60) as gateway,
        httpx.AsyncClient(base_url=upstream_url, timeout=60) as upstream,
    ):
        try:
            rehydration.append(
                await roundtrip.echo_rehydration(toolkit, upstream, samples, notebook)
            )
        except httpx.HTTPError as exc:
            notebook.skipped.append(
                f"rehydration: the echo tool did not answer ({type(exc).__name__})"
            )
        try:
            leak = await roundtrip.leak_check(gateway, upstream, samples)
        except httpx.HTTPError as exc:
            notebook.skipped.append(
                f"upstream leak check: the stack did not answer ({type(exc).__name__})"
            )
    if leak:
        rehydration.append(leak.rehydration)
    return rehydration, leak


async def evaluate(
    toolkit: Toolkit,
    notebook: Notebook,
    *,
    name: str,
    gateway_url: str = GATEWAY_URL,
    upstream_url: str,
) -> EvalResults:
    started = datetime.now(UTC)
    dlp = load("dlp", DlpSample)
    detection = [
        await metrics.detection(toolkit, layers, dlp, notebook) for layers in toolkit.detectors
    ]
    evasion = None
    if toolkit.normalisation_switch:
        evasion = await metrics.evasion(toolkit, load("evasion", EvasionSample), notebook)
    else:
        notebook.skipped.append("evasion: this detector cannot run without normalisation")
    fingerprint = []
    if "default+demo" in toolkit.detectors:
        samples = load("fingerprint", FingerprintSample)
        fingerprint = await metrics.fingerprint(toolkit, samples, notebook)
    else:
        notebook.skipped.append("T2 fingerprints: they need the demo organisation's documents")
    category = [
        score
        for layers in toolkit.detectors
        for score in await metrics.category(
            toolkit, layers, load("category", CategorySample), notebook
        )
    ]
    injection = await metrics.injection(toolkit, load("injection", InjectionSample), notebook)
    scenarios = await metrics.agent_scenarios(toolkit, load("agent_scenarios", AgentScenario))
    rehydration, leak = await _stack_checks(toolkit, dlp, notebook, gateway_url, upstream_url)
    return EvalResults(
        name=name,
        started=started,
        finished=datetime.now(UTC),
        models=toolkit.models,
        split=SPLIT,
        dataset_sizes=sizes(),
        detection=detection,
        evasion=evasion,
        fingerprint=fingerprint,
        category=category,
        injection=injection,
        rehydration=rehydration,
        leak=LeakResult(
            requests_checked=leak.requests_checked if leak else 0,
            upstream_leaks=leak.upstream_leaks if leak else 0,
            tool_destination_leaks=sum(result.real_values_leaked for result in scenarios),
        ),
        latency=metrics.latency(notebook),
        cost_per_1k_prompts_usd=round(notebook.cost_usd / notebook.prompts_costed * 1000, 4),
        agent_scenarios=scenarios,
        misses=notebook.misses,
        skipped=notebook.skipped,
    )


def write_results(results: EvalResults, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{results.name}.json"
    path.write_text(results.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


async def _run(out_dir: Path, layers: tuple[Layers, ...], name: str) -> Path:
    settings = get_settings()
    notebook = Notebook()
    async with AsyncExitStack() as stack:
        toolkit = await build_toolkit(settings, stack, layers, notebook)
        if not toolkit.detectors:
            raise SystemExit(f"Nothing to evaluate: {'; '.join(notebook.skipped)}")
        results = await evaluate(
            toolkit, notebook, name=name, upstream_url=settings.mock_upstream_url
        )
    return write_results(results, out_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.runner", description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the results file")
    parser.add_argument(
        "--layers",
        choices=sorted(LAYER_CHOICES),
        default="both",
        help="protected data to evaluate with: the default pack, default plus demo, or both",
    )
    parser.add_argument(
        "--name",
        default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        help="name of the run and of its file; a timestamp when omitted",
    )
    args = parser.parse_args(argv)
    path = asyncio.run(_run(args.out, LAYER_CHOICES[args.layers], args.name))
    print(f"Wrote {path}")
    return 0
