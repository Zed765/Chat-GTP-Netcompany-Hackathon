"""`fingerprint.jsonl` and `category.jsonl`: the two sets behind the T2 thresholds.

Fingerprint positives are excerpts of corpus documents, word for word, cut short, in other
words and in the other language; its negatives come from documents that are never
fingerprinted. Category samples come from outlines the exemplars were not written from.
"""

from collections.abc import Sequence
from random import Random

from seeder.compose.exemplars import source_documents
from seeder.compose.generic import Outsiders, benign_documents, generic_document
from seeder.compose.library import Document, load_library
from seeder.compose.slots import Language
from seeder.datasets.common import Row, window, with_splits
from seeder.world import World

CATEGORY_KINDS = ("contract", "financial", "health", "hr")
CATEGORY_CODE = ("queue_worker.py", "priceFormatter.ts", "Scheduler.kt", "csv_export.rb")
DOCUMENTS_PER_LIBRARY = 4
LANGUAGES: tuple[Language, Language] = ("en", "el")


def _body(document: Document) -> list[str]:
    """The paragraphs between the title block and the closing lines."""
    return document.paragraphs[2:-1]


def _excerpts(document: Document, count: int, size: int = 2) -> list[str]:
    """`count` runs of consecutive paragraphs, or of lines for source code."""
    if document.kind == "source":
        lines = len(document.text.splitlines())
        return [window(document.text, start) for start in range(0, lines - 25, 15)][:count]
    body = _body(document)
    starts = range(0, len(body) - size + 1, max(1, (len(body) - size) // max(count - 1, 1)))
    return ["\n\n".join(body[start : start + size]) for start in starts][:count]


def _cut(paragraphs: Sequence[str]) -> str:
    """The end of one clause and the start of the next, as a hurried copy and paste gives."""
    first, second = (paragraph.split("\n", 1)[-1] for paragraph in paragraphs[:2])
    return f"{first[len(first) // 2 :]}\n\n{second[: len(second) * 2 // 3]}"


def build_fingerprint(
    corpus: Sequence[Document], holdout: Sequence[Document], exemplars: Sequence[Document]
) -> list[Row]:
    rng = Random("fingerprint")
    rows: list[Row] = []

    def add(text: str, variant: str, source: Document, origin: str | None = None) -> None:
        positive = variant != "negative"
        rows.append(
            {
                "id": f"fingerprint-{len(rows) + 1:03d}",
                "variant": variant,
                "source_document": source.id if positive else None,
                "category": source.category if positive else None,
                "negative_source": origin,
                "language": source.language,
                "kind": source.kind,
                "text": text,
            }
        )

    for document in corpus:
        add(_excerpts(document, 1)[0], "verbatim", document)
        if document.kind != "source":
            add(_cut(_body(document)[3:5]), "partial", document)
        for kind in ("paraphrased", "translated"):
            variants = [variant for variant in document.variants if variant.kind == kind]
            if variants:
                add(rng.choice(variants).text, kind, document)
    for document in holdout:
        for excerpt in _excerpts(document, 3):
            add(excerpt, "negative", document, "holdout")
    boilerplate = [d for d in exemplars if d.category in ("CONTRACT", "SOURCE_CODE")]
    for document in boilerplate[::2]:
        add(_excerpts(document, 1)[0], "negative", document, "boilerplate")
    for document in [d for d in exemplars if d.category == "BENIGN"][::4]:
        add("\n\n".join(document.paragraphs[1:3]), "negative", document, "benign")
    return with_splits(rows, rng, lambda row: str(row["variant"]))


def build_category(world: World) -> list[Row]:
    rng = Random(f"{world.seed}:category")
    outsiders = Outsiders(world, "category")
    rows: list[Row] = []

    def add(text: str, category: str, language: str, kind: str) -> None:
        rows.append(
            {
                "id": f"category-{len(rows) + 1:03d}",
                "category": category,
                "language": language,
                "kind": kind,
                "text": text,
            }
        )

    for kind in CATEGORY_KINDS:
        for language in LANGUAGES:
            library = load_library(f"heldout/{kind}.{language}")
            for index in range(DOCUMENTS_PER_LIBRARY):
                document = generic_document(
                    library, f"{kind}-{index}", outsiders, sections=99, title=index
                )
                if index == 0:
                    add(document.text, library.category, language, "document")
                for excerpt in _excerpts(document, 3):
                    add(excerpt, library.category, language, "excerpt")
    for source in source_documents("heldout", CATEGORY_CODE, "code"):
        add(source.text, "SOURCE_CODE", "en", "document")
        for excerpt in _excerpts(source, 6):
            add(excerpt, "SOURCE_CODE", "en", "excerpt")
    for language in LANGUAGES:
        for document in benign_documents(f"heldout/benign.{language}", "benign", 10, rng):
            add(document.text, "BENIGN", language, "document")
            add("\n\n".join(document.paragraphs[1:3]), "BENIGN", language, "excerpt")
    return with_splits(rows, rng, lambda row: str(row["category"]))
