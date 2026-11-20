"""Clause libraries: the outlines that documents are composed from, kept as YAML in `content/`.

A library is one kind of document in one language. A document takes a title, the header, a
subset of the sections and the footer, with the slots filled from a context.
"""

from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Literal

import yaml
from pydantic import BaseModel

from seeder.compose.slots import Language, Slots, fill

CONTENT = Path(__file__).resolve().parents[1] / "content"


class Section(BaseModel):
    id: str
    heading: str
    text: str
    paraphrase: str | None = None
    translation: str | None = None


class Library(BaseModel):
    kind: str
    category: str
    language: Language
    numbered: bool = False
    titles: list[str]
    header: str = ""
    sections: list[Section]
    footer: str = ""


@dataclass(frozen=True)
class Variant:
    """A clause of a document in other words or in the other language."""

    section: str
    kind: Literal["paraphrased", "translated"]
    text: str


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    kind: str
    category: str
    language: Language
    client: str | None
    text: str
    entities: tuple[str, ...]
    variants: tuple[Variant, ...] = ()
    file: str = ""

    @property
    def paragraphs(self) -> list[str]:
        return [block for block in self.text.split("\n\n") if block.strip()]

    @property
    def words(self) -> int:
        return len(self.text.split())


def load_library(name: str) -> Library:
    """`name` is the path under `content/` without the extension, e.g. `corpus/contract.en`."""
    raw = yaml.safe_load((CONTENT / f"{name}.yaml").read_text(encoding="utf-8"))
    return Library.model_validate(raw)


def _choose(library: Library, rng: Random, count: int) -> list[Section]:
    chosen = set(rng.sample(range(len(library.sections)), k=min(count, len(library.sections))))
    return [section for index, section in enumerate(library.sections) if index in chosen]


def compose(
    library: Library,
    doc_id: str,
    slots: Slots,
    other_slots: Slots,
    rng: Random,
    *,
    sections: int,
    title: int = 0,
    client: str | None = None,
) -> Document:
    """`other_slots` are the same facts in the other language, for translated clauses."""
    blocks: list[str] = []
    entities: list[str] = []
    variants: list[Variant] = []

    def add(template: str, heading: str = "") -> None:
        filled = fill(template.strip(), slots)
        blocks.append(f"{heading}\n{filled.text}" if heading else filled.text)
        entities.extend(filled.entities)

    add(library.titles[title % len(library.titles)])
    if library.header:
        add(library.header)
    for number, section in enumerate(_choose(library, rng, sections), 1):
        add(section.text, f"{number}. {section.heading}" if library.numbered else section.heading)
        if section.paraphrase:
            text = fill(section.paraphrase.strip(), slots).text
            variants.append(Variant(section.id, "paraphrased", text))
        if section.translation:
            text = fill(section.translation.strip(), other_slots).text
            variants.append(Variant(section.id, "translated", text))
    if library.footer:
        add(library.footer)
    return Document(
        id=doc_id,
        title=blocks[0],
        kind=library.kind,
        category=library.category,
        language=library.language,
        client=client,
        text="\n\n".join(blocks) + "\n",
        entities=tuple(dict.fromkeys(entities)),
        variants=tuple(variants),
        file=f"{doc_id}.txt",
    )
