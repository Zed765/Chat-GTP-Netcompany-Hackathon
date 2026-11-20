"""Held-out documents of the same kinds as the corpus. They are never fingerprinted: the
fingerprint evaluation uses them as negatives."""

from dataclasses import replace

from seeder.compose.corpus import source_file_name
from seeder.compose.exemplars import source_documents
from seeder.compose.generic import Outsiders, generic_document
from seeder.compose.library import Document, load_library
from seeder.world import World

HELDOUT_PROSE = (
    "contract.en",
    "contract.el",
    "proposal.en",
    "financial.en",
    "financial.el",
    "meeting.el",
)
HOLDOUT_SOURCES = ("queue_worker.py", "priceFormatter.ts")
ALL_SECTIONS = 99


def build_holdout(world: World) -> list[Document]:
    outsiders = Outsiders(world, "holdout")
    documents = [
        generic_document(
            load_library(f"heldout/{name}"),
            f"holdout-{name.replace('.', '-')}",
            outsiders,
            sections=ALL_SECTIONS,
            title=0,
        )
        for name in HELDOUT_PROSE
    ]
    sources = source_documents("heldout", HOLDOUT_SOURCES, "holdout-source")
    return documents + [
        replace(source, file=source_file_name(source.id, source.title)) for source in sources
    ]
