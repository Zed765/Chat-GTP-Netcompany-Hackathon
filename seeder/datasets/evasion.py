"""`evasion.jsonl`: sensitive values written so that a plain pattern match misses them.

Every sample is a list of turns, because one technique splits a value across two messages.
A label gives the turn it is in, its span there and the clean value behind it.
"""

import base64
import unicodedata
from collections.abc import Callable
from random import Random
from urllib.parse import quote

from seeder import identifiers
from seeder.compose.context import company_of
from seeder.datasets.common import Row, with_splits, zero_width
from seeder.names import person_from
from seeder.world import Client, World

CARRIERS = {
    "en": (
        ("Client detail: ", ". Please check it."),
        ("The value they sent me is ", ". Is it right?"),
    ),
    "el": (
        ("Στοιχείο πελάτη: ", ". Έλεγξέ το, παρακαλώ."),
        ("Η τιμή που μου έστειλαν είναι ", ". Είναι σωστή;"),
    ),
}
SAMPLES_PER_TECHNIQUE = {
    "spaced_digits": 20,
    "fullwidth": 10,
    "zero_width": 20,
    "encoded": 24,
    "split_across_turns": 16,
    "transliterated_names": 20,
}


def _fullwidth(text: str) -> str:
    return "".join(
        chr(ord(char) + 0xFEE0) if char.isalnum() and char.isascii() else char for char in text
    )


def _grouped(text: str, size: int, separator: str) -> str:
    return separator.join(text[index : index + size] for index in range(0, len(text), size))


def _unaccented_capitals(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.upper())
    return "".join(char for char in plain if not unicodedata.combining(char))


def _numbers(rng: Random, client: Client) -> list[tuple[str, str]]:
    return [("AFM", client.afm), ("IBAN", client.iban), ("CARD", identifiers.make_card(rng))]


def _names(client: Client) -> list[tuple[str, str, str]]:
    """(type, Greek form, Latin form) of a Greek client's names."""
    contact = person_from(client.contacts[0].name)
    names = [("PERSON", contact.name, contact.latin)]
    if client.kind == "company":
        company = company_of(client)
        names.append(("ORG", company.trade_name, company.latin))
    return names


def _spaced(rng: Random, value: str) -> str:
    separator = rng.choice((" ", "-", "."))
    return _grouped(value, rng.choice((1, 3)), separator)


def _encoded(rng: Random, data_type: str, value: str) -> str:
    sentence = f"{data_type} {value}"
    encoding = rng.choice(("base64", "hex", "url") if not value.isascii() else ("base64", "hex"))
    if encoding == "base64":
        return base64.b64encode(sentence.encode()).decode()
    return sentence.encode().hex() if encoding == "hex" else quote(sentence)


def build_evasion(world: World) -> list[Row]:
    rng = Random(f"{world.seed}:evasion")
    greek_clients = [client for client in world.clients if client.language == "el"]
    rows: list[Row] = []

    def carrier() -> tuple[str, tuple[str, str]]:
        language = rng.choice(("en", "el"))
        return language, rng.choice(CARRIERS[language])

    def add(technique: str, language: str, turns: list[str], labels: list[Row]) -> None:
        for label in labels:
            label["text"] = turns[label["turn"]][label["start"] : label["end"]]
        rows.append(
            {
                "id": f"evasion-{len(rows) + 1:03d}",
                "technique": technique,
                "language": language,
                "turns": turns,
                "labels": labels,
            }
        )

    def one_turn(technique: str, data_type: str, value: str, shown: str, client: Client) -> None:
        language, (before, after) = carrier()
        label = {"turn": 0, "start": len(before), "end": len(before) + len(shown),
                 "type": data_type, "value": value, "client": client.id}  # fmt: skip
        add(technique, language, [f"{before}{shown}{after}"], [label])

    transforms: dict[str, Callable[[str], str]] = {
        "spaced_digits": lambda value: _spaced(rng, value),
        "fullwidth": _fullwidth,
        "zero_width": zero_width,
    }
    for technique, transform in transforms.items():
        for _ in range(SAMPLES_PER_TECHNIQUE[technique]):
            client = rng.choice(world.clients)
            data_type, value = rng.choice(_numbers(rng, client))
            one_turn(technique, data_type, value, transform(value), client)
    for _ in range(SAMPLES_PER_TECHNIQUE["encoded"]):
        client = rng.choice(greek_clients)
        values = [*_numbers(rng, client)[:2], ("EMAIL", client.email), _names(client)[0][:2]]
        data_type, value = rng.choice(values)
        one_turn("encoded", data_type, value, _encoded(rng, data_type, value), client)
    for _ in range(SAMPLES_PER_TECHNIQUE["split_across_turns"]):
        client = rng.choice(world.clients)
        data_type, value = rng.choice([*_numbers(rng, client)[:2], ("EMAIL", client.email)])
        cut = len(value) // 2
        language, (before, after) = carrier()
        first = {"turn": 0, "start": len(before), "end": len(before) + cut, "type": data_type,
                 "value": value, "client": client.id, "fragment": True}  # fmt: skip
        second = {**first, "turn": 1, "start": 0, "end": len(value) - cut}
        turns = [f"{before}{value[:cut]}", f"{value[cut:]}{after}"]
        add("split_across_turns", language, turns, [first, second])
    for index in range(SAMPLES_PER_TECHNIQUE["transliterated_names"]):
        client = rng.choice(greek_clients)
        data_type, greek, latin = rng.choice(_names(client))
        shown = latin if index % 2 else _unaccented_capitals(greek)
        one_turn("transliterated_names", data_type, greek, shown, client)
    return with_splits(rows, rng, lambda row: str(row["technique"]))
