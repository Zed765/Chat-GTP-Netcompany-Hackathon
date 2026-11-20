"""Reads and validates term lists. Each row is judged on its own, so one bad row does not
stop the rest from being imported."""

import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from gateway.app.core.types import DataType
from gateway.app.detect.fingerprint import normalise_category
from gateway.app.protected.errors import InvalidInputError
from gateway.app.protected.schemas import RowError

MAX_TERM_CHARS = 200
MIN_TERM_CHARS = 2
MAX_ALIASES = 20
MAX_GROUP_CHARS = 80
MAX_ROWS = 20_000
DEFAULT_TERM_TYPE = DataType.CLIENT

_DATA_TYPE = re.compile(r"[A-Z][A-Z0-9_]{1,59}")
_ALIAS_SEPARATOR = re.compile(r"[;|]")
_ENCODINGS = ("utf-8-sig", "cp1253")


@dataclass(frozen=True, slots=True)
class NewTerm:
    term: str
    aliases: tuple[str, ...]
    data_type: str
    group: str


def span_type(raw: object) -> str:
    """A data type for terms and patterns: a built-in span type or a company's own."""
    name = normalise_category(str(raw))
    if not _DATA_TYPE.fullmatch(name):
        raise ValueError("data_type must be 2 to 60 letters, digits or underscores")
    if name in DataType.CATEGORIES:
        raise ValueError(f"{name} is a document category, not a type of value")
    return name


def document_category(raw: str) -> str:
    name = normalise_category(raw)
    if not _DATA_TYPE.fullmatch(name):
        raise InvalidInputError("The category must be 2 to 60 letters, digits or underscores")
    if name in DataType.SPAN_TYPES:
        raise InvalidInputError(f"{name} is a type of value, not a document category")
    return name


def _text(raw: object, what: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{what} must be text")
    value = " ".join(raw.split())
    if not MIN_TERM_CHARS <= len(value) <= MAX_TERM_CHARS:
        raise ValueError(f"{what} must be {MIN_TERM_CHARS} to {MAX_TERM_CHARS} characters long")
    if not any(char.isalnum() for char in value):
        raise ValueError(f"{what} must contain a letter or a digit")
    return value


def _aliases(raw: object) -> list[str]:
    if raw is None or raw == "":
        return []
    items = _ALIAS_SEPARATOR.split(raw) if isinstance(raw, str) else raw
    if not isinstance(items, list) or len(items) > MAX_ALIASES:
        raise ValueError(f"aliases must be a list of at most {MAX_ALIASES} names")
    return [_text(item, "an alias") for item in items if item not in ("", None)]


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[NewTerm], list[RowError]]:
    """Rows are numbered from 1, as a person counts them."""
    valid: list[NewTerm] = []
    errors: list[RowError] = []
    for number, row in enumerate(rows, start=1):
        try:
            data_type = span_type(row.get("data_type") or DEFAULT_TERM_TYPE)
            group = str(row.get("group") or data_type.lower().replace("_", "-"))
            valid.append(
                NewTerm(
                    term=_text(row.get("term"), "term"),
                    aliases=tuple(_aliases(row.get("aliases"))),
                    data_type=data_type,
                    group=group[:MAX_GROUP_CHARS],
                )
            )
        except ValueError as problem:
            errors.append(RowError(row=number, message=str(problem)))
    return valid, errors


def _decode(content: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InvalidInputError("The file is not text in UTF-8 or Windows-1253")


def parse_term_file(filename: str, content: bytes) -> list[dict[str, Any]]:
    """A JSON list of objects (or of plain names), or a CSV file with a `term` column."""
    text = _decode(content)
    if filename.lower().endswith(".json") or text.lstrip().startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as problem:
            raise InvalidInputError(f"The file is not valid JSON: {problem.msg}") from problem
        if not isinstance(data, list):
            raise InvalidInputError("The JSON file must hold a list of terms")
        rows = [item if isinstance(item, dict) else {"term": item} for item in data]
    else:
        # Spreadsheets in a Greek locale export with semicolons.
        header = text.partition("\n")[0]
        delimiter = ";" if header.count(";") > header.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        columns = [(name or "").strip().lower() for name in reader.fieldnames or []]
        if "term" not in columns:
            raise InvalidInputError("The CSV file needs a header row with a `term` column")
        reader.fieldnames = columns
        rows = [dict(row) for row in reader]
    if len(rows) > MAX_ROWS:
        raise InvalidInputError(f"A term list can hold at most {MAX_ROWS} rows")
    return rows
