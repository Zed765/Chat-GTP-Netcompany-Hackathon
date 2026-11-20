"""Shared pieces of the evaluation-set builders: label rows, obfuscations and the split."""

from collections import defaultdict
from collections.abc import Callable, Sequence
from random import Random
from typing import Any

from seeder.compose.slots import Filled, Label

Row = dict[str, Any]
HELD_OUT_SHARE = 0.3
ZERO_WIDTH = "​"
ATTACKER = "audit@external-review.example"


def label_row(label: Label) -> Row:
    return {
        "start": label.start,
        "end": label.end,
        "type": label.type,
        "text": label.text,
        "client": label.client,
        "form": label.form,
    }


def label_rows(filled: Filled) -> list[Row]:
    return [label_row(label) for label in filled.labels]


def with_splits(rows: Sequence[Row], rng: Random, key: Callable[[Row], str]) -> list[Row]:
    """Hold out 30% of each group for reporting; thresholds are tuned on the rest."""
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[key(row)].append(index)
    held_out: set[int] = set()
    for indices in groups.values():
        rng.shuffle(indices)
        held_out.update(indices[: round(len(indices) * HELD_OUT_SHARE)])
    return [
        {**row, "split": "test" if index in held_out else "train"} for index, row in enumerate(rows)
    ]


def zero_width(text: str, every: int = 3) -> str:
    """Hide a value from a plain pattern match by putting zero-width spaces inside it."""
    pieces = [text[index : index + every] for index in range(0, len(text), every)]
    return ZERO_WIDTH.join(pieces)


def window(text: str, start: int, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[start : start + lines])
