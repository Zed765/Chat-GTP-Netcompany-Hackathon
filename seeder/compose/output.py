"""Writes generated documents and JSONL files. Output is byte-for-byte reproducible."""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from seeder.compose.library import Document


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) + "\n" for row in rows]
    path.write_text("".join(lines), encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_documents(directory: Path, documents: Sequence[Document], fields: Sequence[str]) -> None:
    """Replace the directory's files with these documents and a `manifest.jsonl` of `fields`."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.iterdir():
        if stale.is_file():
            stale.unlink()
    for document in documents:
        (directory / document.file).write_text(document.text, encoding="utf-8")
    write_jsonl(
        directory / "manifest.jsonl",
        ({field: getattr(document, field) for field in fields} for document in documents),
    )
