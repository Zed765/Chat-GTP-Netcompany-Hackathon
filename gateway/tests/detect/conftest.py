"""A local engine built from the default pack plus a small invented company, without a database."""

from pathlib import Path

import pytest

from gateway.app.core.types import LocalDetection, RowSource
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.ner import NerEngine
from gateway.app.detect.patterns import PatternRule
from gateway.app.detect.terms import TermRule
from gateway.app.protected.pack import load_pattern_pack, load_term_pack

DEFAULTS = Path(__file__).resolve().parents[3] / "defaults"

COMPANY_TERMS = (
    TermRule(
        "client-1",
        "Helios Shipping S.A.",
        ("Helios Shipping", "Ήλιος Ναυτιλιακή", "HSA"),
        "CLIENT",
        RowSource.SYNCED,
        "crm-clients",
    ),
    TermRule("contact-1", "Μαρία Παπαδοπούλου", (), "PERSON", RowSource.SYNCED, "crm-contacts"),
    TermRule("project-1", "Project Kerveros", (), "PROJECT", RowSource.UPLOADED, "project"),
)
COMPANY_PATTERNS = (
    PatternRule(
        "pattern-1", "project-code", r"\bPRJ-[0-9]{4}\b", "PROJECT", RowSource.SEEDED, "custom"
    ),
)


def default_terms() -> list[TermRule]:
    pack, _ = load_term_pack(DEFAULTS)
    return [
        TermRule(f"{group.name}:{index}", term, (), group.data_type, RowSource.DEFAULT, group.name)
        for group in pack.groups
        for index, term in enumerate(group.terms)
    ]


def default_patterns() -> list[PatternRule]:
    pack, _ = load_pattern_pack(DEFAULTS)
    return [
        PatternRule(
            entry.name,
            entry.name,
            entry.regex,
            entry.data_type or group.data_type,
            RowSource.DEFAULT,
            group.name,
        )
        for group in pack.groups
        for entry in group.patterns
    ]


@pytest.fixture(scope="session")
def ner() -> NerEngine:
    return NerEngine()


@pytest.fixture(scope="session")
def engine(ner: NerEngine) -> LocalEngine:
    return LocalEngine(
        [*default_patterns(), *COMPANY_PATTERNS], [*default_terms(), *COMPANY_TERMS], ner
    )


@pytest.fixture(scope="session")
def rules_only() -> LocalEngine:
    """T0 and the term matcher without the language models, for tests that need neither."""
    return LocalEngine(
        [*default_patterns(), *COMPANY_PATTERNS], [*default_terms(), *COMPANY_TERMS], None
    )


def found(result: LocalDetection) -> list[tuple[str, str]]:
    return [(finding.data_type, finding.text) for finding in result.findings]
