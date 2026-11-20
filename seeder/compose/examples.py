"""The "Try an example" prompts of the Chat page, filled with the scene 1 client."""

from collections.abc import Sequence
from random import Random
from typing import Any

import yaml

from seeder import fake_secrets
from seeder.compose.context import client_party, party_slots
from seeder.compose.corpus import LANGUAGES
from seeder.compose.library import CONTENT, Document
from seeder.compose.slots import Slot, fill, plain
from seeder.world import World

EXCERPT_CLAUSES = 2


def contract_excerpt(corpus: Sequence[Document], language: str) -> str:
    """Two numbered clauses, word for word, from the first contract in that language."""
    contract = next(d for d in corpus if d.kind == "contract" and d.language == language)
    clauses = [paragraph for paragraph in contract.paragraphs if paragraph[0].isdigit()]
    return "\n\n".join(clauses[2 : 2 + EXCERPT_CLAUSES])


def build_examples(world: World, corpus: Sequence[Document]) -> list[dict[str, Any]]:
    rng = Random(f"{world.seed}:examples")
    secrets: dict[str, Slot] = {
        name: plain(make(rng)) for name, make in fake_secrets.SECRET_MAKERS.items()
    }
    party = client_party(world.scene_client)
    entries = yaml.safe_load((CONTENT / "examples.yaml").read_text(encoding="utf-8"))
    examples = []
    for entry in entries:
        for language in LANGUAGES:
            slots = {
                **party_slots(party, language),
                **secrets,
                "excerpt": plain(contract_excerpt(corpus, language)),
            }
            text = entry[language]
            examples.append(
                {
                    "id": f"chat-{entry['id']}-{language}",
                    "page": "chat",
                    "language": language,
                    "title": text["title"],
                    "prompt": fill(text["prompt"], slots).text,
                    "tool": entry["tool"],
                    "expected": entry["expected"],
                    "note": text["note"],
                }
            )
    return examples
