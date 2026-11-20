"""The committed evaluation sets: sizes, exact labels and the held-out split."""

import base64
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from seeder import identifiers
from seeder.compose.corpus import build_corpus
from seeder.compose.exemplars import build_exemplars
from seeder.compose.heldout import build_holdout
from seeder.datasets.dlp import build_dlp
from seeder.datasets.documents import build_category, build_fingerprint
from seeder.datasets.evasion import build_evasion
from seeder.datasets.injection import build_agent_scenarios, build_injection
from seeder.world import DATA_DIR, build_world

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
Rows = list[dict[str, Any]]


def load(name: str) -> Rows:
    lines = (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_committed_sets_are_what_the_generator_writes() -> None:
    world = build_world()
    corpus, holdout, exemplars = build_corpus(world), build_holdout(world), build_exemplars(world)
    assert load("dlp") == build_dlp(world)
    assert load("evasion") == build_evasion(world)
    assert load("injection") == build_injection(world)
    assert load("fingerprint") == build_fingerprint(corpus, holdout, exemplars)
    assert load("category") == build_category(world)
    assert load("agent_scenarios") == build_agent_scenarios(world)


@pytest.mark.parametrize(
    ("name", "minimum"),
    [("dlp", 400), ("evasion", 100), ("injection", 150), ("fingerprint", 120), ("category", 150)],
)
def test_each_set_is_large_enough_and_holds_out_thirty_per_cent(name: str, minimum: int) -> None:
    rows = load(name)
    assert len(rows) >= minimum
    assert len({row["id"] for row in rows}) == len(rows)
    held_out = sum(row["split"] == "test" for row in rows) / len(rows)
    assert 0.27 <= held_out <= 0.33
    assert {row["split"] for row in rows} == {"train", "test"}


def test_dlp_labels_point_at_exactly_the_text_they_name() -> None:
    for row in load("dlp"):
        end = 0
        for label in row["labels"]:
            assert row["text"][label["start"] : label["end"]] == label["text"], row["id"]
            assert label["start"] >= end, f"{row['id']}: labels overlap"
            end = label["end"]


def test_dlp_mixes_languages_and_keeps_a_third_negative() -> None:
    rows = load("dlp")
    assert {row["language"] for row in rows} == {"en", "el", "greeklish", "mixed"}
    negatives = [row for row in rows if row["negative"]]
    assert 0.30 <= len(negatives) / len(rows) <= 0.40
    assert all(not row["labels"] and not row["categories"] for row in negatives)
    families = {row["group"] for row in rows if row["group"].startswith("hard_negative")}
    assert families == {
        f"hard_negative:{name}"
        for name in ("invalid_afm", "order_number", "code_no_secret", "harmless_base64",
                     "earlier_version", "non_client_org")
    }  # fmt: skip
    for row in rows:
        if row["group"] == "hard_negative:invalid_afm":
            (number,) = re.findall(r"\b\d{9}\b", row["text"])
            assert not identifiers.is_valid_afm(number)
        if row["group"] == "hard_negative:non_client_org":
            assert [label["type"] for label in row["labels"]] == ["ORG"]
            assert row["labels"][0]["client"] is None


def test_dlp_names_are_half_clients_in_every_form_and_half_outsiders() -> None:
    world = build_world()
    names = [
        label
        for row in load("dlp")
        for label in row["labels"]
        if label["type"] in ("PERSON", "ORG")
    ]
    clients = [label for label in names if label["client"]]
    assert 0.35 <= len(clients) / len(names) <= 0.65
    assert {label["form"] for label in clients} == {"exact", "inflected", "greeklish", "alias"}
    assert len({label["client"] for label in clients}) >= 35
    known = {client.id: client for client in world.clients}
    for label in clients:
        client = known[label["client"]]
        if label["form"] == "alias":
            assert label["text"] == client.aliases[0]
        if label["form"] == "exact" and label["type"] == "ORG":
            assert label["text"] in (client.trade_name, client.legal_name)


def test_dlp_identifiers_are_valid_and_types_are_the_expected_ones() -> None:
    labels = [label for row in load("dlp") for label in row["labels"]]
    assert {label["type"] for label in labels} == {
        "PERSON", "ORG", "AFM", "IBAN", "EMAIL", "PHONE", "ADDRESS", "AMKA", "CARD", "ID_CARD",
        "SECRET", "CONFIDENTIAL_MARKER", "PROJECT_CODE",
    }  # fmt: skip
    for label in labels:
        if label["type"] == "AFM":
            assert identifiers.is_valid_afm(label["text"])
        if label["type"] == "IBAN":
            assert identifiers.is_valid_iban(label["text"])
        if label["type"] == "AMKA":
            assert identifiers.is_valid_amka(label["text"])
        if label["type"] == "CARD":
            assert identifiers.luhn_is_valid(label["text"])
    documents = [row for row in load("dlp") if row["categories"]]
    assert {row["categories"][0] for row in documents} == {
        "CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE",
    }  # fmt: skip


def _plain(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z@.]", "", unicodedata.normalize("NFKC", text))


def test_evasion_labels_hide_the_value_they_claim() -> None:
    rows = load("evasion")
    assert {row["technique"] for row in rows} == {
        "spaced_digits", "fullwidth", "zero_width", "encoded", "split_across_turns",
        "transliterated_names",
    }  # fmt: skip
    for row in rows:
        shown = [
            row["turns"][label["turn"]][label["start"] : label["end"]] for label in row["labels"]
        ]
        assert shown == [label["text"] for label in row["labels"]]
        value = row["labels"][0]["value"]
        technique = row["technique"]
        if technique in ("spaced_digits", "fullwidth", "zero_width"):
            assert shown[0] != value
            assert _plain(shown[0]).replace(".", "") == value.replace(".", "")
        elif technique == "split_across_turns":
            assert len(row["turns"]) == 2 and "".join(shown) == value
        elif technique == "encoded":
            decoded = [unquote(shown[0])]
            for decode in (base64.b64decode, bytes.fromhex):
                try:
                    decoded.append(decode(shown[0]).decode())
                except ValueError:
                    continue
            assert any(value in text for text in decoded), row["id"]
        else:
            assert shown[0] != value and row["labels"][0]["type"] in ("PERSON", "ORG")


def test_injection_has_both_classes_in_every_carrier_and_language() -> None:
    rows = load("injection")
    seen = Counter((row["label"], row["carrier"], row["language"]) for row in rows)
    for carrier in ("chat", "document", "web_page", "email"):
        for language in ("en", "el"):
            assert seen["injection", carrier, language] >= 5
            assert seen["benign", carrier, language] >= 5
    assert {row["kind"] for row in rows if row["label"] == "injection"} == {"direct", "indirect"}
    assert sum(row["technique"] == "lookalike" for row in rows) >= 25
    hidden = [row for row in rows if row["technique"] in ("html_comment", "hidden_element")]
    assert all("<!--" in row["text"] or "display:none" in row["text"] for row in hidden)


def test_fingerprint_positives_come_from_the_corpus_and_negatives_do_not() -> None:
    rows = load("fingerprint")
    corpus = {
        row["id"]: (DATA_DIR / "corpus" / row["file"]).read_text(encoding="utf-8")
        for row in map(
            json.loads, (DATA_DIR / "corpus" / "manifest.jsonl").read_text().splitlines()
        )
    }
    variants = Counter(row["variant"] for row in rows)
    assert all(
        variants[name] >= 20 for name in ("verbatim", "partial", "paraphrased", "translated")
    )
    assert variants["negative"] >= 40
    for row in rows:
        if row["variant"] == "verbatim":
            assert row["text"] in corpus[row["source_document"]]
        elif row["variant"] == "partial":
            first, second = row["text"].split("\n\n")
            assert (
                first in corpus[row["source_document"]] and second in corpus[row["source_document"]]
            )
        elif row["variant"] in ("paraphrased", "translated"):
            assert row["text"] not in corpus[row["source_document"]]
        else:
            assert row["source_document"] is None
            assert not any(row["text"] in text for text in corpus.values())
        if row["variant"] == "translated":
            greek = bool(re.search("[α-ω]", row["text"]))
            assert greek == (row["language"] == "en")
    assert {row["negative_source"] for row in rows if row["variant"] == "negative"} == {
        "holdout", "boilerplate", "benign",
    }  # fmt: skip


def test_category_covers_six_categories_in_both_languages() -> None:
    rows = load("category")
    counts = Counter(row["category"] for row in rows)
    assert set(counts) == {"CONTRACT", "FINANCIAL", "HEALTH", "HR", "SOURCE_CODE", "BENIGN"}
    assert min(counts.values()) >= 20
    prose = Counter(row["language"] for row in rows if row["category"] != "SOURCE_CODE")
    assert prose["en"] == prose["el"]
    exemplar_dir = DATASETS.parents[1] / "defaults" / "exemplars"
    exemplars = [path.read_text(encoding="utf-8") for path in exemplar_dir.iterdir()]
    assert not any(row["text"] in text for row in rows for text in exemplars)


def test_agent_scenarios_name_what_must_not_leak() -> None:
    rows = load("agent_scenarios")
    assert len(rows) >= 10
    assert {row["language"] for row in rows} == {"en", "el"}
    for row in rows:
        assert all(value in row["record"] for value in row["values"])
        assert row["destination"] in ("trusted", "untrusted") and row["side_effects"] is True
    assert sum(not row["expect_flagged"] for row in rows) == 1
