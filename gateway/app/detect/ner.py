"""Names of people, organisations and places, and street addresses, through Presidio.

spaCy's small English and Greek models do the statistical part. Each stretch of text goes to
the model of its own script, because either model produces noise on the other language.
"""

import re
import threading
from collections.abc import Iterator
from functools import cache
from typing import Any, cast

from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from gateway.app.core.textnorm import fold
from gateway.app.core.types import DataType, Tier
from gateway.app.detect.spans import Span

ENGLISH, GREEK = "en", "el"
MODELS = (
    {"lang_code": ENGLISH, "model_name": "en_core_web_sm"},
    {"lang_code": GREEK, "model_name": "el_core_news_sm"},
)
NER_SCORE = 0.85
ORG_SCORE = 0.6
LOCATION_SCORE = 0.6
# Above the model's score: Presidio drops a result inside a higher-scored one of its type.
LEGAL_FORM_SCORE = 0.9
ADDRESS_SCORE = 0.75
ADDRESS_WITH_POSTCODE_SCORE = 0.9
ORG_RECOGNISER = "org:legal-form"
ADDRESS_RECOGNISER = "address"

_TYPES = {
    "PERSON": DataType.PERSON,
    "ORGANIZATION": DataType.ORG,
    "LOCATION": DataType.LOCATION,
    "ADDRESS": DataType.ADDRESS,
}
_NER_SCORES = {
    DataType.PERSON: NER_SCORE,
    DataType.ORG: ORG_SCORE,
    DataType.LOCATION: LOCATION_SCORE,
}
_LABELS = {"PERSON": "PERSON", "ORG": "ORGANIZATION", "GPE": "LOCATION", "LOC": "LOCATION"}

_CAPITAL = r"[A-ZΑ-ΩΆΈΉΊΌΎΏ]"
_NAME_WORD = rf"{_CAPITAL}[\w&'’\-]*\.?"
_LEGAL_FORM = (
    r"(?:S\.?A\.?|A\.?E\.?|Α\.?Ε\.?(?:Β\.?Ε\.?)?|Α\.?Β\.?Ε\.?Ε\.?|Ε\.?Π\.?Ε\.?|Ι\.?Κ\.?Ε\.?|Ο\.?Ε\.?"
    r"|Ε\.?Ε\.?|I\.?K\.?E\.?|E\.?P\.?E\.?|Ltd\.?|Limited|Inc\.?|LLC|LLP|PLC|GmbH|Corp\.?|B\.V\.|AG)"
)
# A name may start only where no name character precedes it. Without that, a run such as
# "A-A-A-" could be entered at every capital and read to its end each time.
_NAME_START = r"(?<![\w&'’\-])"
_ORG_WITH_LEGAL_FORM = rf"{_NAME_START}(?:{_NAME_WORD}[ \t]+){{1,4}}{_LEGAL_FORM}(?![\w])"

_STREET_GR = r"(?:[Οο]δ(?:ός|ό|ού|\.)|[Λλ]εωφ(?:όρος|όρο|όρου|\.)|Λ\.|[Ππ]λ(?:ατεία|ατείας|\.))"
_STREET_LATIN = r"(?:[Oo]dos|[Ll]eof(?:oros|\.)|[Pp]lateia)"
_STREET_EN = (
    r"(?:Street|Str\.?|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Lane|Drive|Square|Sq\.?)"
)
_HOUSE_NUMBER = r"\d{1,4}[A-Za-zΑ-Ωα-ω]?(?:-\d{1,4})?(?![\w])"
_POSTCODE = r"(?:(?:Τ\.?Κ\.?|T\.?K\.?|GR)[ \-]?)?\d{3}[ ]?\d{2}(?![\d])"
_CITY = rf"(?:,?[ \t]+{_CAPITAL}\w+)?"
_STREET_NAME = rf"(?:{_NAME_WORD}[ \t]+){{1,4}}"
_ADDRESS_WITH_STREET_WORD = (
    rf"{_NAME_START}(?:{_STREET_GR}|{_STREET_LATIN})[ \t]+{_STREET_NAME}{_HOUSE_NUMBER}"
    rf"(?:,?[ \t]+{_POSTCODE}{_CITY})?"
)
_ADDRESS_WITH_POSTCODE = (
    rf"{_NAME_START}{_STREET_NAME}(?:{_STREET_EN}[ \t]+)?{_HOUSE_NUMBER},?[ \t]+{_POSTCODE}{_CITY}"
)
_COUNTRY = rf"(?:,[ \t]+{_CAPITAL}\w+)?"
_ADDRESS_NUMBER_FIRST = (
    rf"(?<![\w]){_HOUSE_NUMBER}[ \t]+{_STREET_NAME}{_STREET_EN}(?![\w])"
    rf"(?:,?[ \t]+{_POSTCODE}{_CITY}{_COUNTRY})?"
)

# Words the small models often mistake for an organisation or a place.
_NOT_A_NAME = frozenset(
    fold(word)
    for word in (
        "AFM", "ΑΦΜ", "AMKA", "ΑΜΚΑ", "IBAN", "BIC", "SWIFT", "VAT", "ΦΠΑ", "ΑΔΤ", "API", "URL",
        "PDF", "SQL", "JSON", "XML", "CSV", "HTML", "ID", "AI", "GDPR", "CRM", "ERP", "KPI", "NDA",
        "SLA", "FAQ", "PIN", "OTP", "ΤΚ", "Τηλ", "Email", "E-mail", "Fax", "Python", "Java",
    )
)  # fmt: skip
_EDGE_PUNCTUATION = " \t\n\r,;:!?()[]{}\"'«»“”‘’-–—"
_GREEK_LETTER = re.compile(r"[Ͱ-Ͽἀ-῿]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[^\W\d_]+")
_UNBROKEN_RUN = re.compile(r"\S{101,}")
# camelCase and the punctuation of program code: an identifier, not a name.
_CODE_LIKE = re.compile(r"[a-z][A-Z]|[(){}\[\]=:;<>_]")


def _pattern_recognisers(language: str) -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="ORGANIZATION",
            name=ORG_RECOGNISER,
            supported_language=language,
            patterns=[Pattern("legal form", _ORG_WITH_LEGAL_FORM, LEGAL_FORM_SCORE)],
            global_regex_flags=re.MULTILINE,
        ),
        PatternRecognizer(
            supported_entity="ADDRESS",
            name=ADDRESS_RECOGNISER,
            supported_language=language,
            patterns=[
                Pattern("street word", _ADDRESS_WITH_STREET_WORD, ADDRESS_SCORE),
                Pattern("postcode", _ADDRESS_WITH_POSTCODE, ADDRESS_WITH_POSTCODE_SCORE),
                Pattern("number first", _ADDRESS_NUMBER_FIRST, ADDRESS_SCORE),
            ],
            global_regex_flags=re.MULTILINE,
        ),
    ]


def language_segments(text: str) -> Iterator[tuple[int, int, str]]:
    """Runs of consecutive lines in one script, as (start, end, language)."""
    start = position = 0
    current: str | None = None
    for line in text.splitlines(keepends=True):
        greek = len(_GREEK_LETTER.findall(line))
        latin = len(_LATIN_LETTER.findall(line))
        if greek or latin:
            language = GREEK if greek >= latin else ENGLISH
            if current is not None and language != current:
                yield start, position, current
                start = position
            current = language
        position += len(line)
    if position > start:
        yield start, position, current or ENGLISH


class NerEngine:
    """Loads both models once. `find` is safe to call from worker threads."""

    def __init__(self) -> None:
        nlp_engine = SpacyNlpEngine(
            models=list(MODELS),
            ner_model_configuration=NerModelConfiguration(
                model_to_presidio_entity_mapping=_LABELS,
                low_score_entity_names=[],
                default_score=NER_SCORE,
            ),
        )
        nlp_engine.load()
        # Name recognition has its own token vectors, so tagging, parsing and lemmas
        # would only add time.
        for pipeline in cast(dict[str, Any], nlp_engine.nlp).values():
            pipeline.select_pipes(enable=["ner"])
        registry = RecognizerRegistry(supported_languages=[ENGLISH, GREEK])
        for language in (ENGLISH, GREEK):
            registry.add_recognizer(
                SpacyRecognizer(
                    supported_language=language,
                    supported_entities=["PERSON", "ORGANIZATION", "LOCATION"],
                    ner_strength=NER_SCORE,
                )
            )
            for recogniser in _pattern_recognisers(language):
                registry.add_recognizer(recogniser)
        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine, registry=registry, supported_languages=[ENGLISH, GREEK]
        )
        # spaCy's vocabulary is shared mutable state, so one text is analysed at a time.
        self._lock = threading.Lock()

    def find(self, text: str) -> list[Span]:
        # spaCy's tokeniser splits a long unbroken run one character at a time, at a
        # cost that grows with the square of its length. No name is that long.
        text = _UNBROKEN_RUN.sub(lambda run: " " * len(run.group()), text)
        spans: list[Span] = []
        for start, end, language in language_segments(text):
            with self._lock:
                results = self._analyzer.analyze(
                    text=text[start:end], language=language, entities=list(_TYPES)
                )
            for result in results:
                span = _clean(text, start, result, language)
                if span is not None:
                    spans.append(span)
        return spans


def _clean(text: str, offset: int, result: RecognizerResult, language: str) -> Span | None:
    """Trim a recognised span and drop it when it cannot be a name or an address."""
    data_type = _TYPES[result.entity_type]
    start, end = offset + result.start, offset + result.end
    while start < end and text[start] in _EDGE_PUNCTUATION:
        start += 1
    while end > start and text[end - 1] in _EDGE_PUNCTUATION:
        end -= 1
    recogniser = result.recognition_metadata[RecognizerResult.RECOGNIZER_NAME_KEY]
    if recogniser in (ORG_RECOGNISER, ADDRESS_RECOGNISER):
        return Span(data_type, start, end, Tier.T1, result.score, recogniser)
    if data_type == DataType.PERSON:
        start, end = _trim_to_capitalised(text, start, end)
    value = text[start:end]
    words = _WORD.findall(value)
    if not words or "\n" in value or any(char.isdigit() for char in value):
        return None
    if not any(word[0].isupper() for word in words) or _CODE_LIKE.search(value):
        return None
    if fold(value) in _NOT_A_NAME or (data_type == DataType.ORG and len(words) < 2):
        return None
    return Span(data_type, start, end, Tier.T1, _NER_SCORES[data_type], f"ner:{language}")


def _trim_to_capitalised(text: str, start: int, end: int) -> tuple[int, int]:
    """A person's name starts and ends with a capitalised word."""
    words = [match for match in _WORD.finditer(text, start, end) if match.group()[0].isupper()]
    if not words:
        return start, start
    return words[0].start(), words[-1].end()


@cache
def shared_ner_engine() -> NerEngine:
    """One engine per process: the models are large and never change."""
    return NerEngine()
