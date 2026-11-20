"""`make data`: regenerates the world, the corpus, the exemplars and the evaluation sets.

Everything is composed offline from a fixed seed, so the output is identical on every run
and the build never needs an API key. With `--rewrite` and a key, the offline model
rewrites the prose around the entities first.
"""

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from openai import OpenAI

from seeder.compose.corpus import build_corpus
from seeder.compose.examples import build_examples
from seeder.compose.exemplars import build_exemplars
from seeder.compose.heldout import build_holdout
from seeder.compose.library import Document
from seeder.compose.output import write_documents, write_json, write_jsonl
from seeder.compose.rewrite import OpenAIModel, TextModel, rewrite_document
from seeder.datasets.dlp import build_dlp
from seeder.datasets.documents import build_category, build_fingerprint
from seeder.datasets.evasion import build_evasion
from seeder.datasets.injection import build_agent_scenarios, build_injection
from seeder.world import DATA_DIR, build_world, write_world

REPO = Path(__file__).resolve().parents[1]
EXEMPLARS_DIR = REPO / "defaults" / "exemplars"
EXAMPLES_FILE = REPO / "defaults" / "examples.json"
DATASETS_DIR = REPO / "eval" / "datasets"
CORPUS_FIELDS = ("id", "file", "title", "category", "language", "client", "kind")
EXEMPLAR_FIELDS = ("id", "file", "category", "language")
HOLDOUT_FIELDS = ("id", "file", "title", "category", "language", "kind")

log = logging.getLogger("seeder.generate")


OPENAI_BASE_URL = "https://api.openai.com/v1"


def _model(parser: argparse.ArgumentParser) -> TextModel:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        parser.error("--rewrite needs OPENAI_API_KEY")
    client = OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL)
    return OpenAIModel(client, os.environ.get("ASPIDA_MODEL_OFFLINE", "gpt-5-mini"))


def rewritten(documents: Sequence[Document], model: TextModel | None) -> list[Document]:
    """Prose goes through the model when there is one; source code never does."""
    if model is None:
        return list(documents)
    return [
        document if document.kind == "source" else rewrite_document(model, document)
        for document in documents
    ]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="rewrite the prose with the model named by ASPIDA_MODEL_OFFLINE (needs a key)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    model = _model(parser) if args.rewrite else None

    world = build_world()
    write_world(world)
    log.info("world: %d employees, %d clients", len(world.employees), len(world.clients))

    corpus = rewritten(build_corpus(world), model)
    write_documents(DATA_DIR / "corpus", corpus, CORPUS_FIELDS)
    log.info("corpus: %d documents", len(corpus))

    exemplars = rewritten(build_exemplars(world), model)
    write_documents(EXEMPLARS_DIR, exemplars, EXEMPLAR_FIELDS)
    log.info("exemplars: %d documents", len(exemplars))

    holdout = rewritten(build_holdout(world), model)
    write_documents(DATASETS_DIR / "holdout_corpus", holdout, HOLDOUT_FIELDS)
    log.info("held-out corpus: %d documents", len(holdout))

    write_json(EXAMPLES_FILE, build_examples(world, corpus))

    datasets = {
        "dlp": build_dlp(world, model),
        "evasion": build_evasion(world),
        "injection": build_injection(world),
        "fingerprint": build_fingerprint(corpus, holdout, exemplars),
        "category": build_category(world),
        "agent_scenarios": build_agent_scenarios(world),
    }
    for name, rows in datasets.items():
        write_jsonl(DATASETS_DIR / f"{name}.jsonl", rows)
        log.info("%s: %d samples", name, len(rows))


if __name__ == "__main__":
    main()
