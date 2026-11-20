import json
from collections import Counter
from pathlib import Path

import pytest

from gateway.app.proxy.schemas import Example
from seeder.compose.corpus import build_corpus
from seeder.compose.examples import build_examples
from seeder.compose.exemplars import build_exemplars
from seeder.compose.heldout import build_holdout
from seeder.compose.library import Document
from seeder.generate import DATASETS_DIR, EXAMPLES_FILE, EXEMPLARS_DIR
from seeder.world import DATA_DIR, World, build_world

CORPUS_DIR = DATA_DIR / "corpus"
HOLDOUT_DIR = DATASETS_DIR / "holdout_corpus"


@pytest.fixture(scope="module")
def world() -> World:
    return build_world()


@pytest.fixture(scope="module")
def corpus(world: World) -> list[Document]:
    return build_corpus(world)


def _manifest(directory: Path) -> list[dict[str, str]]:
    lines = (directory / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.mark.parametrize("directory", [CORPUS_DIR, EXEMPLARS_DIR, HOLDOUT_DIR])
def test_each_manifest_lists_exactly_the_files_in_its_directory(directory: Path) -> None:
    rows = _manifest(directory)
    files = {path.name for path in directory.iterdir()} - {"manifest.jsonl"}
    assert {row["file"] for row in rows} == files
    assert len({row["id"] for row in rows}) == len(rows)


def test_committed_documents_are_what_the_generator_writes(
    world: World, corpus: list[Document]
) -> None:
    generated = {
        CORPUS_DIR: corpus,
        EXEMPLARS_DIR: build_exemplars(world),
        HOLDOUT_DIR: build_holdout(world),
    }
    for directory, documents in generated.items():
        for document in documents:
            assert (directory / document.file).read_text(encoding="utf-8") == document.text


def test_the_corpus_has_the_planned_mix(corpus: list[Document]) -> None:
    assert Counter(document.kind for document in corpus) == {
        "contract": 12,
        "proposal": 8,
        "financial": 6,
        "meeting": 6,
        "source": 8,
    }
    prose = [document for document in corpus if document.kind != "source"]
    assert Counter(document.language for document in prose) == {"el": 16, "en": 16}
    assert all(400 <= document.words <= 1500 for document in corpus)
    assert corpus[0].client == "C001" and corpus[0].category == "CONTRACT"
    assert {row["category"] for row in _manifest(CORPUS_DIR)} == {
        "CONTRACT",
        "CLIENT_CONFIDENTIAL",
        "FINANCIAL",
        "SOURCE_CODE",
    }


def test_no_python_source_is_stored_with_a_py_extension() -> None:
    for directory in (CORPUS_DIR, HOLDOUT_DIR):
        assert not list(directory.glob("*.py"))


def test_exemplars_cover_every_category_in_both_languages(world: World) -> None:
    rows = _manifest(EXEMPLARS_DIR)
    assert Counter(row["category"] for row in rows) == {
        "CONTRACT": 12,
        "FINANCIAL": 12,
        "HEALTH": 12,
        "HR": 12,
        "SOURCE_CODE": 12,
        "BENIGN": 30,
    }
    assert set(rows[0]) == {"id", "file", "category", "language"}
    prose = [row for row in rows if row["category"] != "SOURCE_CODE"]
    assert Counter(row["language"] for row in prose) == {"el": 39, "en": 39}
    extensions = {row["file"].rsplit(".", 1)[1] for row in rows if row["category"] == "SOURCE_CODE"}
    assert len(extensions) >= 8
    assert all(300 <= document.words <= 800 for document in build_exemplars(world))


def test_generic_documents_name_nobody_from_the_world(world: World) -> None:
    known = {employee.display_name for employee in world.employees}
    for client in world.clients:
        known |= {client.legal_name, client.trade_name, *client.aliases}
        known |= {contact.name for contact in client.contacts}
    for document in build_exemplars(world) + build_holdout(world):
        assert not [name for name in known if name in document.text], document.id


def test_the_held_out_corpus_has_eight_documents_of_the_corpus_kinds(world: World) -> None:
    holdout = build_holdout(world)
    assert Counter(document.kind for document in holdout) == {
        "contract": 2,
        "proposal": 1,
        "financial": 2,
        "meeting": 1,
        "source": 2,
    }
    assert all(document.words >= 400 for document in holdout)


def test_every_entity_put_into_a_document_is_in_its_text(
    world: World, corpus: list[Document]
) -> None:
    for document in corpus + build_exemplars(world) + build_holdout(world):
        assert all(entity in document.text for entity in document.entities), document.id
    contract = corpus[0]
    client = world.scene_client
    for value in (client.legal_name, client.afm, client.iban, client.address, client.email):
        assert value in contract.entities


def test_examples_show_every_action_in_both_languages(world: World, corpus: list[Document]) -> None:
    committed = json.loads(EXAMPLES_FILE.read_text(encoding="utf-8"))
    assert committed == build_examples(world, corpus)
    examples = [Example.model_validate(entry) for entry in committed]
    shown = Counter((e["tool"], e["expected"], e["language"]) for e in committed)
    for language in ("en", "el"):
        assert shown["chatterbox-ai", "redact", language] == 1
        assert shown["chatterbox-ai", "block", language] == 1
        assert shown["draftpilot", "warn", language] == 1
        assert shown["chatterbox-ai", "allow", language] == 1
        assert shown["athena-assist", "block", language] == 1
        assert shown["athena-assist", "allow", language] == 1
    assert all(example.page == "chat" for example in examples)


def test_scene_one_uses_the_client_from_the_crm(world: World) -> None:
    examples = {entry["id"]: entry for entry in json.loads(EXAMPLES_FILE.read_text("utf-8"))}
    client = world.scene_client
    greek = examples["chat-client-email-unapproved-el"]["prompt"]
    english = examples["chat-client-email-unapproved-en"]["prompt"]
    assert client.legal_name in greek and client.contacts[0].name in greek
    assert client.aliases[1] in english and "Maria Papadopoulou" in english
    for prompt in (greek, english):
        assert client.afm in prompt and client.iban[:4] in prompt
    assert examples["chat-client-email-approved-en"]["prompt"] == english
    warning = examples["chat-marked-confidential-tolerated-en"]["prompt"]
    assert "CONFIDENTIAL" in warning and client.afm not in warning
