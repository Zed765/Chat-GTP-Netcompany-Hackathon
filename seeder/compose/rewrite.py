"""The path for when an API key exists: a model rewrites the text around the entities.

Entities never reach the model. Each is swapped for a numbered token first and swapped
back afterwards, and the result is kept only if every entity survived; otherwise the
offline text stands.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from openai import OpenAI

from seeder.compose.library import Document
from seeder.compose.slots import Filled, Label, Language

log = logging.getLogger("seeder.rewrite")

_TOKEN = re.compile(r"⟦(\d+)⟧")
_LANGUAGE_NAMES: dict[Language, str] = {"el": "Greek", "en": "English"}
_INSTRUCTIONS = (
    "Rewrite the following {language} text in natural, correct {language}, as a different "
    "author would have written the same document. Keep the meaning, the structure, the "
    "headings, every number and every date. Tokens such as ⟦3⟧ stand for names and "
    "identifiers: keep each one exactly as written, exactly once per occurrence, in a place "
    "where the sentence still reads correctly. Return only the rewritten text."
)


class TextModel(Protocol):
    def rewrite(self, instructions: str, text: str) -> str: ...


class OpenAIModel:
    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def rewrite(self, instructions: str, text: str) -> str:
        response = self._client.responses.create(
            model=self._model, instructions=instructions, input=text, store=False
        )
        return response.output_text


def _token(index: int) -> str:
    return f"⟦{index}⟧"


def entities_survive(text: str, entities: Sequence[str]) -> bool:
    return all(entity in text for entity in entities)


def rewrite_text(model: TextModel, text: str, entities: Sequence[str], language: Language) -> str:
    """Rewrite a document. Every entity string must still be in the result."""
    ordered = sorted(set(entities), key=len, reverse=True)
    shielded = text
    for index, entity in enumerate(ordered):
        shielded = shielded.replace(entity, _token(index))
    answer = model.rewrite(_INSTRUCTIONS.format(language=_LANGUAGE_NAMES[language]), shielded)
    try:
        restored = _TOKEN.sub(lambda match: ordered[int(match[1])], answer)
    except IndexError:
        restored = ""
    if restored and entities_survive(restored, ordered):
        return restored
    log.warning("a rewrite lost an entity; keeping the offline text")
    return text


def rewrite_document(model: TextModel, document: Document) -> Document:
    return replace(
        document, text=rewrite_text(model, document.text, document.entities, document.language)
    )


def rewrite_filled(model: TextModel, filled: Filled, language: Language) -> Filled:
    """Rewrite a labelled prompt. Each label must come back exactly once, and keeps its span."""
    shielded = filled.text
    for index, label in sorted(enumerate(filled.labels), key=lambda item: -item[1].start):
        shielded = shielded[: label.start] + _token(index) + shielded[label.end :]
    answer = model.rewrite(_INSTRUCTIONS.format(language=_LANGUAGE_NAMES[language]), shielded)
    seen = [int(match[1]) for match in _TOKEN.finditer(answer)]
    if sorted(seen) != list(range(len(filled.labels))):
        log.warning("a rewrite lost or repeated a label; keeping the offline text")
        return filled
    parts: list[str] = []
    labels: list[Label] = []
    length = cursor = 0
    for match in _TOKEN.finditer(answer):
        label = filled.labels[int(match[1])]
        literal = answer[cursor : match.start()]
        parts += [literal, label.text]
        start = length + len(literal)
        labels.append(replace(label, start=start, end=start + len(label.text)))
        length = start + len(label.text)
        cursor = match.end()
    parts.append(answer[cursor:])
    return Filled("".join(parts), tuple(labels))
