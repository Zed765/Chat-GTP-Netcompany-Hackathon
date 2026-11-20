"""`dlp.jsonl`: prompts with entity-level labels, exact by construction.

About half the people and organisations are clients from the CRM, in several forms; the
rest are outsiders, so the precision of `CLIENT` can be measured. A third of the prompts
hold nothing sensitive, among them the hard negatives.
"""

from random import Random

from seeder.compose.generic import Outsiders, generic_slots
from seeder.compose.library import CONTENT, load_library
from seeder.compose.prompts import SLOT_LANGUAGE, PromptFactory, load_prompts
from seeder.compose.rewrite import TextModel, rewrite_filled
from seeder.compose.slots import Filled, Language, fill, join_filled
from seeder.datasets.common import Row, label_rows, window, with_splits
from seeder.world import World

CLIENT_FILLS = {"en": 3, "el": 3, "greeklish": 3, "mixed": 3}
OUTSIDER_FILLS = 1
BENIGN_FILLS = 5
HARD_NEGATIVE_FILLS = {
    "invalid_afm": 5,
    "order_number": 3,
    "code_no_secret": 1,
    "harmless_base64": 4,
    "earlier_version": 1,
    "non_client_org": 6,
}
DOCUMENT_KINDS = {"contract": "CONTRACT", "financial": "FINANCIAL", "health": "HEALTH", "hr": "HR"}
CODE_FILES = ("Scheduler.kt", "csv_export.rb", "queue_worker.py", "priceFormatter.ts")


def _document_samples(world: World) -> list[tuple[Filled, str, str]]:
    """Excerpts that carry a document category as well as entities."""
    outsiders = Outsiders(world, "dlp-documents")
    samples: list[tuple[Filled, str, str]] = []
    languages: tuple[Language, Language] = ("en", "el")
    for kind, category in DOCUMENT_KINDS.items():
        for language in languages:
            library = load_library(f"heldout/{kind}.{language}")
            for start in (0, 3, 6):
                slots = generic_slots(outsiders, language)
                parts = [fill(s.text.strip(), slots) for s in library.sections[start : start + 2]]
                if start == 0:
                    parts.insert(0, fill(library.header.strip(), slots))
                samples.append((join_filled(parts), language, category))
    for name in CODE_FILES:
        code = (CONTENT / "code" / "heldout" / f"{name}.tmpl").read_text(encoding="utf-8")
        samples += [(Filled(window(code, start), ()), "en", "SOURCE_CODE") for start in (0, 30)]
    return samples


def build_dlp(world: World, model: TextModel | None = None) -> list[Row]:
    """With a model, the text around the entities of the sensitive prompts is rewritten."""
    rng = Random(f"{world.seed}:dlp")
    factory = PromptFactory(world)
    library = load_prompts()
    rows: list[Row] = []

    def add(filled: Filled, language: str, group: str, categories: tuple[str, ...] = ()) -> None:
        if model and group in ("client", "outsider"):
            filled = rewrite_filled(model, filled, SLOT_LANGUAGE[language])
        rows.append(
            {
                "id": f"dlp-{len(rows) + 1:04d}",
                "language": language,
                "group": group,
                "text": filled.text,
                "labels": label_rows(filled),
                "categories": list(categories),
                "negative": not filled.labels and not categories,
            }
        )

    for group, templates in library.sensitive.items():
        for template in templates:
            for _ in range(CLIENT_FILLS[group]):
                client = factory.client_for(rng, template)
                add(factory.about_client(template, group, rng, client), group, "client")
            for _ in range(OUTSIDER_FILLS):
                add(factory.about_outsider(template, group, rng), group, "outsider")
    for language, templates in library.secrets.items():
        for template in templates:
            for _ in range(4):
                add(factory.about_outsider(template, language, rng), language, "secret")
    for language, templates in library.marked.items():
        for template in templates:
            for _ in range(2):
                add(factory.about_outsider(template, language, rng), language, "marked")
    for language, templates in library.benign.items():
        for template in templates:
            for _ in range(BENIGN_FILLS):
                add(factory.about_outsider(template, language, rng), language, "benign")
    for family, by_language in library.hard_negatives.items():
        for language, templates in by_language.items():
            for template in templates:
                for _ in range(HARD_NEGATIVE_FILLS[family]):
                    filled = factory.about_outsider(template, language, rng)
                    add(filled, language, f"hard_negative:{family}")
    for filled, document_language, category in _document_samples(world):
        add(filled, document_language, "document", (category,))
    return with_splits(rows, rng, lambda row: str(row["group"]))
