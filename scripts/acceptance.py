"""Acceptance checks for the brief, against the running stack: `make acceptance`.

`make smoke` covers the employee and admin scenes. This covers the rest of what the brief
asks for: each check changes something an admin can change, proves the next request behaves
differently with no restart, and puts things back. The models answer for real, so the checks
assert what the gateway does and stores, never what a model wrote.
"""

import asyncio
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx
import yaml

from scripts.sample_log import lines
from scripts.smoke import SCENE_1, Stack, stored_values

PROJECT = "Project Halcyon"
MARKED = "Strictly confidential: the draft budget for next year."
DOCUMENT_LABEL = "Acceptance check agreement"
DOCUMENT = " ".join(
    f"Clause {n}. The Supplier shall deliver the Kestrel-{n} reconciliation ledger to the "
    f"Purchaser within {n + 3} working days of each quarter end, together with the signed "
    f"variance statement for cost centre {4100 + n}, and shall keep both for seven years."
    for n in range(1, 13)
)
EXCERPT = DOCUMENT[: len(DOCUMENT) // 2]


def _test(stack: Stack, text: str) -> dict[str, Any]:
    result: dict[str, Any] = stack.call(
        "admin", "POST", "/api/protected/test", json={"text": text}
    ).json()
    return result


def _types(result: dict[str, Any]) -> set[str]:
    return {finding["data_type"] for finding in result["findings"]}


def _matched_documents(stack: Stack) -> set[str]:
    """Labels of the protected documents an excerpt of the test document matches."""
    return {c["match_label"] for c in _test(stack, EXCERPT)["categories"] if c["match_label"]}


def _scene_1_action(stack: Stack) -> str:
    example = stack.examples("chat")[SCENE_1[0]]
    return str(stack.chat(example).json()["aspida"]["action"])


def check_log_upload_updates_usage_and_queues_only_drafts(stack: Stack) -> None:
    """Whether an unknown site is an AI tool is the model's call. What the gateway owes is
    the usage count, and that whatever is queued is an unreviewed draft of the model."""
    before = stack.call("admin", "GET", "/api/tools/chatgpt").json()["requests_14d"]
    content = "\n".join(lines(time.time())).encode()
    upload = {"file": ("acceptance.log", content, "text/plain")}
    result = stack.call(
        "admin", "POST", "/api/discovery/logs", files=upload, data={"kind": "squid"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["matched"] > 0 and not result.json()["duplicate"], result.text
    after = stack.call("admin", "GET", "/api/tools/chatgpt").json()["requests_14d"]
    assert after > before, "usage of a known tool did not grow"
    queue = stack.call("admin", "GET", "/api/discovery/queue").json()
    queued = {tool["slug"]: tool for tool in queue}
    for slug in result.json()["new_tool_slugs"]:
        assert slug in queued, f"{slug} was discovered and is not in the review queue"
        assert queued[slug]["status"] == "unknown" and queued[slug]["needs_review"]
        assert queued[slug]["rating_source"] == "model_drafted", queued[slug]


def check_status_change_alters_the_next_decision(stack: Stack) -> None:
    tool = "/api/tools/chatterbox-ai"
    assert _scene_1_action(stack) == "redact"
    try:
        stack.call("admin", "PATCH", tool, json={"status": "approved"}).raise_for_status()
        assert _scene_1_action(stack) == "allow", "approving the tool changed nothing"
    finally:
        stack.call("admin", "PATCH", tool, json={"status": "unapproved"}).raise_for_status()
    assert _scene_1_action(stack) == "redact"


def check_policy_edit_applies_at_once_and_replay_shows_it(stack: Stack) -> None:
    original = stack.call("admin", "GET", "/api/policy").json()["yaml"]
    draft = yaml.safe_load(original)
    for rule in draft["rules"]:
        if rule["name"] == "pii-and-client-data":
            rule["action"] = "block"
    stricter = yaml.safe_dump(draft, sort_keys=False, allow_unicode=True)
    replay = stack.call("admin", "POST", "/api/policy/replay", json={"yaml": stricter, "days": 7})
    assert replay.status_code == 200 and replay.json()["changed"] > 0, replay.text
    try:
        activated = stack.call("admin", "POST", "/api/policy/activate", json={"yaml": stricter})
        assert activated.status_code == 200, activated.text
        assert _scene_1_action(stack) == "block", "the stricter policy did not apply"
    finally:
        stack.call("admin", "POST", "/api/policy/activate", json={"yaml": original})
    assert _scene_1_action(stack) == "redact"


def check_default_group_can_be_switched_off(stack: Stack) -> None:
    summary = stack.call("admin", "GET", "/api/protected/summary").json()
    markers = next(
        group["group"]
        for store in summary["stores"]
        if store["store"] == "terms"
        for group in store["groups"]
        if group["data_type"] == "CONFIDENTIAL_MARKER" and group["source"] == "default"
    )
    switch = f"/api/protected/groups/terms/{markers}"
    assert "CONFIDENTIAL_MARKER" in _types(_test(stack, MARKED))
    try:
        stack.call("admin", "PATCH", switch, json={"enabled": False}).raise_for_status()
        assert "CONFIDENTIAL_MARKER" not in _types(_test(stack, MARKED)), "the switch did nothing"
    finally:
        stack.call("admin", "PATCH", switch, json={"enabled": True}).raise_for_status()
    assert "CONFIDENTIAL_MARKER" in _types(_test(stack, MARKED))


def check_term_import_changes_detection(stack: Stack) -> None:
    question = f"What is the status of {PROJECT}?"
    assert "PROJECT" not in _types(_test(stack, question))
    term = [{"term": PROJECT, "data_type": "PROJECT"}]
    imported = stack.call("admin", "POST", "/api/protected/terms", json=term).json()
    assert imported["imported"] == 1, imported
    try:
        assert "PROJECT" in _types(_test(stack, question)), "the imported term is not detected"
    finally:
        found = stack.call("admin", "GET", f"/api/protected/terms?q={PROJECT}").json()["items"]
        for row in found:
            stack.call("admin", "DELETE", f"/api/protected/terms/{row['id']}")
    assert "PROJECT" not in _types(_test(stack, question))


def check_document_upload_is_detected_and_its_text_is_kept_nowhere(stack: Stack) -> None:
    assert DOCUMENT_LABEL not in _matched_documents(stack), "left over from an earlier run"
    upload = {"file": ("agreement.txt", DOCUMENT.encode(), "text/plain")}
    form = {"label": DOCUMENT_LABEL, "category": "CONTRACT"}
    uploaded = stack.call("admin", "POST", "/api/protected/documents", files=upload, data=form)
    assert uploaded.status_code == 200, uploaded.text
    try:
        assert DOCUMENT_LABEL in _matched_documents(stack), "the upload is not detected"
        kept = asyncio.run(stored_values({"Kestrel-7 reconciliation ledger"}))
        assert not kept, "; ".join(kept)
    finally:
        document_id = uploaded.json()["document"]["id"]
        stack.call("admin", "DELETE", f"/api/protected/documents/{document_id}")


def check_only_an_admin_looks_up_who_sent_an_event(stack: Stack) -> None:
    event = stack.call("admin", "GET", "/api/events?limit=1").json()["items"][0]
    identity = f"/api/events/{event['id']}/identity"
    assert stack.call("employee", "GET", identity).status_code == 403
    assert stack.call("admin", "GET", identity).json()["user_id"]


CHECKS: tuple[Callable[[Stack], None], ...] = (
    check_log_upload_updates_usage_and_queues_only_drafts,
    check_status_change_alters_the_next_decision,
    check_policy_edit_applies_at_once_and_replay_shows_it,
    check_default_group_can_be_switched_off,
    check_term_import_changes_detection,
    check_document_upload_is_detected_and_its_text_is_kept_nowhere,
    check_only_an_admin_looks_up_who_sent_an_event,
)


def main() -> int:
    failures = 0
    with httpx.Client(timeout=120) as client:
        stack = Stack(client)
        for check in CHECKS:
            try:
                check(stack)
            except (AssertionError, httpx.HTTPError, KeyError, StopIteration) as exc:
                failures += 1
                print(f"FAIL {check.__name__}: {exc!r}")
            else:
                print(f"ok   {check.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
