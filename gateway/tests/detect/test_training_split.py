"""Detection on the training split of the evaluation sets, with the demo organisation loaded
as the CRM source would load it. The held-out rows are never read here.

Run with `-s` to print recall per data type and per form.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from eval.runner.scoring import Span, Tally, is_found
from gateway.app.core.types import RowSource
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.ner import NerEngine
from gateway.app.detect.patterns import PatternRule
from gateway.app.detect.terms import TermRule
from gateway.app.protected.imports import validate_rows
from gateway.app.protected.term_source import terms_from_clients
from gateway.tests.detect.conftest import default_patterns, default_terms

REPO = Path(__file__).resolve().parents[3]
DATASETS = REPO / "eval" / "datasets"
CLIENTS = REPO / "seeder" / "data" / "clients.json"
NAME_TYPES = ("PERSON", "ORG")
PROJECT_CODE = PatternRule(
    "seeded",
    "Project code",
    r"\bPRJ-[A-Z]{3}-[0-9]{4}\b",
    "PROJECT_CODE",
    RowSource.SEEDED,
    "custom",
)


def _report(*parts: object) -> None:
    """Shown by `pytest -s`."""
    sys.stdout.write(" ".join(str(part) for part in parts) + "\n")


def _train(name: str) -> list[dict[str, Any]]:
    path = DATASETS / name
    if not path.is_file() or not CLIENTS.is_file():
        pytest.skip("the evaluation sets and the demo data are not in this checkout")
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [row for row in rows if row["split"] == "train"]


def _span(label: dict[str, Any]) -> Span:
    is_client = label.get("client") is not None and label["type"] in NAME_TYPES
    return Span(label["start"], label["end"], label["type"], is_client)


@pytest.fixture(scope="module")
def demo_engine(ner: NerEngine) -> LocalEngine:
    if not CLIENTS.is_file():
        pytest.skip("the demo data is not in this checkout")
    terms, errors = validate_rows(terms_from_clients(json.loads(CLIENTS.read_text("utf-8"))))
    assert not errors
    crm = [
        TermRule(
            f"crm-{number}", term.term, term.aliases, term.data_type, RowSource.SYNCED, term.group
        )
        for number, term in enumerate(terms)
    ]
    return LocalEngine([*default_patterns(), PROJECT_CODE], [*default_terms(), *crm], ner)


def test_names_and_identifiers_on_the_training_split(demo_engine: LocalEngine) -> None:
    tally = Tally()
    forms: Counter[tuple[str, str]] = Counter()
    for row in _train("dlp.jsonl"):
        findings = [
            Span(finding.start, finding.end, finding.data_type)
            for finding in demo_engine.detect(row["text"]).findings
        ]
        tally.add_spans([_span(label) for label in row["labels"]], findings)
        claims = [finding for finding in findings if finding.type == "CLIENT"]
        for label in row["labels"]:
            if label.get("client") is not None and label["type"] in NAME_TYPES:
                outcome = "found" if is_found(_span(label), claims) else "missed"
                forms[(f"{label['type']}/{label['form']}", outcome)] += 1
    for score in tally.by_type():
        _report(f"{score.data_type:22s} P {score.precision:.2f} R {score.recall:.2f}")
    recall_by_form = {
        form: forms[(form, "found")] / (forms[(form, "found")] + forms[(form, "missed")])
        for form in sorted({form for form, _ in forms})
    }
    _report("CLIENT recall by form:", recall_by_form)

    assert min(recall_by_form.values()) >= 0.95
    by_type = {score.data_type: score for score in tally.by_type()}
    assert by_type["ORG"].recall >= 0.9 and by_type["PERSON"].recall >= 0.95
    assert by_type["CONFIDENTIAL_MARKER"].precision >= 0.8
    overall = tally.overall()
    assert overall.precision >= 0.97 and overall.recall >= 0.97


def test_evasion_on_the_training_split(demo_engine: LocalEngine) -> None:
    found: Counter[tuple[str, bool]] = Counter()
    for row in _train("evasion.jsonl"):
        detections = [demo_engine.detect(turn) for turn in row["turns"]]
        for label in row["labels"]:
            findings = [
                Span(finding.start, finding.end, finding.data_type)
                for finding in detections[label["turn"]].findings
            ]
            found[(row["technique"], is_found(_span(label), findings))] += 1
    recall = {
        technique: found[(technique, True)] / (found[(technique, True)] + found[(technique, False)])
        for technique in sorted({technique for technique, _ in found})
    }
    _report("evasion recall:", recall)
    # A value split over two messages is not detectable one message at a time.
    for technique in (
        "spaced_digits",
        "fullwidth",
        "zero_width",
        "encoded",
        "transliterated_names",
    ):
        assert recall[technique] >= 0.9, technique
