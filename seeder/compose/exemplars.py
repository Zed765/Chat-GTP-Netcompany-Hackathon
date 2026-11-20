"""The default pack's category exemplars: generic documents that name nobody real."""

from random import Random

from seeder.compose.corpus import LANGUAGES
from seeder.compose.generic import Outsiders, benign_documents, generic_document
from seeder.compose.library import CONTENT, Document, load_library
from seeder.world import World

PROSE_KINDS = ("contract", "financial", "health", "hr")
PER_LANGUAGE = 6
SECTIONS = 8
BENIGN_PER_LANGUAGE = 15
SOURCE_FILES = (
    "inventory.py",
    "text_stats.py",
    "todoStore.js",
    "weatherClient.ts",
    "LibraryCatalogue.java",
    "ShoppingCart.cs",
    "ratelimit.go",
    "matrix.rs",
    "bookshop.sql",
    "backup.sh",
    "lru_cache.cpp",
    "ContactForm.php",
)


def source_documents(directory: str, names: tuple[str, ...], prefix: str) -> list[Document]:
    documents = []
    for number, name in enumerate(names, 1):
        doc_id = f"{prefix}-{number:02d}"
        documents.append(
            Document(
                id=doc_id,
                title=name,
                kind="source",
                category="SOURCE_CODE",
                language="en",
                client=None,
                text=(CONTENT / "code" / directory / f"{name}.tmpl").read_text(encoding="utf-8"),
                entities=(),
                file=f"{doc_id}-{name}",
            )
        )
    return documents


def build_exemplars(world: World) -> list[Document]:
    outsiders = Outsiders(world, "exemplars")
    documents = [
        generic_document(
            load_library(f"exemplars/{kind}.{language}"),
            f"{kind}-{language}-{index + 1:02d}",
            outsiders,
            sections=SECTIONS,
            title=index,
        )
        for kind in PROSE_KINDS
        for language in LANGUAGES
        for index in range(PER_LANGUAGE)
    ]
    rng = Random(f"{world.seed}:benign-exemplars")
    for language in LANGUAGES:
        documents += benign_documents(
            f"exemplars/benign.{language}", "benign", BENIGN_PER_LANGUAGE, rng
        )
    return documents + source_documents("exemplars", SOURCE_FILES, "code")
