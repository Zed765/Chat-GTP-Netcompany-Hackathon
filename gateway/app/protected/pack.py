"""Reads the default pack in `defaults/`: terms, patterns and category exemplars."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from gateway.app.core.types import DataType

TERMS_FILE = "terms.yaml"
PATTERNS_FILE = "patterns.yaml"
EXEMPLARS_DIR = "exemplars"
EXEMPLAR_MANIFEST = "manifest.jsonl"
DIGEST_CHARS = 8


class TermGroup(BaseModel):
    name: str
    data_type: str
    terms: list[str]


class TermPack(BaseModel):
    pack_version: str
    groups: list[TermGroup]


class PatternEntry(BaseModel):
    name: str
    regex: str
    data_type: str | None = None
    must_match: str
    must_not_match: str


class PatternGroup(BaseModel):
    name: str
    data_type: str = DataType.SECRET
    patterns: list[PatternEntry]


class PatternPack(BaseModel):
    pack_version: str
    groups: list[PatternGroup]


class Exemplar(BaseModel):
    id: str
    file: str
    category: str
    language: str | None = None
    text: str = Field(default="", exclude=True)


def content_version(declared: str, *contents: bytes) -> str:
    """The declared version plus a digest of the content, so an edited pack always reloads."""
    digest = hashlib.sha256()
    for content in contents:
        digest.update(content)
    return f"{declared}+{digest.hexdigest()[:DIGEST_CHARS]}"


def load_term_pack(defaults_dir: Path) -> tuple[TermPack, str]:
    raw = (defaults_dir / TERMS_FILE).read_bytes()
    pack = TermPack.model_validate(yaml.safe_load(raw))
    return pack, content_version(pack.pack_version, raw)


def load_pattern_pack(defaults_dir: Path) -> tuple[PatternPack, str]:
    raw = (defaults_dir / PATTERNS_FILE).read_bytes()
    pack = PatternPack.model_validate(yaml.safe_load(raw))
    return pack, content_version(pack.pack_version, raw)


def load_exemplars(defaults_dir: Path) -> list[Exemplar]:
    """The category exemplars with their text. An absent or empty directory gives none."""
    manifest = defaults_dir / EXEMPLARS_DIR / EXEMPLAR_MANIFEST
    if not manifest.is_file():
        return []
    exemplars: list[Exemplar] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        exemplar = Exemplar.model_validate(json.loads(line))
        path = manifest.parent / exemplar.file
        if path.is_file():
            exemplars.append(exemplar.model_copy(update={"text": path.read_text("utf-8")}))
    return exemplars
