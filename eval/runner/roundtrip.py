"""Checks that need the running stack: placeholders restored after a round trip, and no
masked value in anything the fake AI tools recorded."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

import httpx

from eval.runner.harness import Notebook, Toolkit, conversation
from eval.runner.samples import DlpSample
from eval.runner.scoring import rate
from eval.schema import RehydrationResult

PLACEHOLDER = re.compile(r"<[A-Z][A-Z_]*_\d+>")
CHUNK_CHARS = 7
SAMPLE_LIMIT = 60
LEAK_TOOL = "chatterbox-ai"
EMPLOYEE = "v.tsioutsias"


@dataclass(frozen=True)
class LeakCheck:
    requests_checked: int
    upstream_leaks: int
    rehydration: RehydrationResult


def _with_data(samples: Sequence[DlpSample]) -> list[DlpSample]:
    return [sample for sample in samples if sample.labels][:SAMPLE_LIMIT]


async def echo_rehydration(
    toolkit: Toolkit, upstream: httpx.AsyncClient, samples: Sequence[DlpSample], notebook: Notebook
) -> RehydrationResult:
    """Mask, send to the echo tool, and restore the reply as it arrives in small chunks."""
    exact = sent = returned = responses = 0
    for sample in _with_data(samples):
        scope = conversation()
        local = await toolkit.best_detector.detect_local(sample.text)
        masked = await toolkit.vault.mask(scope, sample.text, local.findings)
        placeholders = {span.placeholder for span in masked.spans}
        if placeholders:
            body = {"model": "echo", "messages": [{"role": "user", "content": masked.text}]}
            response = await upstream.post("/tools/echo/v1/chat/completions", json=body)
            reply = response.raise_for_status().json()["choices"][0]["message"]["content"]
            rehydrator = await toolkit.vault.rehydrator(scope, placeholders)
            chunks = [reply[i : i + CHUNK_CHARS] for i in range(0, len(reply), CHUNK_CHARS)]
            restored = "".join(rehydrator.feed(chunk) for chunk in chunks) + rehydrator.flush()
            report = rehydrator.report()
            responses += 1
            exact += restored == sample.text
            sent += report.sent
            returned += report.returned
            if restored != sample.text:
                note = f"restored text differs; unresolved: {list(report.unresolved)}"
                notebook.miss(
                    "rehydration", sample.id, "false_negative", "PLACEHOLDER", restored, note
                )
        await toolkit.vault.end(scope)
    return RehydrationResult(
        responses=responses,
        restored_exactly=rate(exact, responses),
        placeholder_survival=rate(returned, sent),
        upstream="echo",
    )


async def leak_check(
    gateway: httpx.AsyncClient, upstream: httpx.AsyncClient, samples: Sequence[DlpSample]
) -> LeakCheck:
    """Send prompts through the gateway to an unapproved tool, then look for any value the
    gateway masked in what the tool received, and count the placeholders its model returned."""
    session = await gateway.post("/api/demo/login", json={"user_id": EMPLOYEE})
    headers = {
        "Authorization": f"Bearer {session.raise_for_status().json()['token']}",
        "X-Aspida-Tool": LEAK_TOOL,
    }
    (await upstream.delete("/recordings")).raise_for_status()
    # What the gateway replaced in each forwarded request, under a tag the request carries
    # as its model name, so other traffic to the same tool cannot be mistaken for it.
    masked_by_tag: dict[str, set[str]] = {}
    run = uuid4().hex[:8]
    forwarded = exact = sent = returned = 0
    for index, sample in enumerate(_with_data(samples)):
        tag = f"leak-check-{run}-{index}"
        body = {"model": tag, "messages": [{"role": "user", "content": sample.text}]}
        scope = {"X-Aspida-Conversation": conversation()}
        response = await gateway.post("/v1/chat/completions", json=body, headers=headers | scope)
        if response.status_code in (403, 409):
            continue
        answer = response.raise_for_status().json()
        trace, summary = answer["aspida"], answer["aspida_summary"]
        masked = trace["action"] == "redact"
        masked_by_tag[tag] = {
            sample.text[span["start"] : span["end"]]
            for span in trace["spans"]
            if masked and span["placeholder"]
        }
        forwarded += 1
        content = answer["choices"][0]["message"]["content"] or ""
        report = summary["rehydration"]
        exact += not report["unresolved"] and not PLACEHOLDER.search(content)
        sent += report["sent"]
        returned += report["returned"]
    recordings = (await upstream.get("/recordings", params={"tool": LEAK_TOOL})).raise_for_status()
    leaks = sum(
        value in json.dumps(row["body"], ensure_ascii=False)
        for row in recordings.json()
        for value in masked_by_tag.get(row["body"].get("model"), ())
    )
    return LeakCheck(
        requests_checked=forwarded,
        upstream_leaks=leaks,
        rehydration=RehydrationResult(
            responses=forwarded,
            restored_exactly=rate(exact, forwarded),
            placeholder_survival=rate(returned, sent),
            upstream="live model",
        ),
    )
