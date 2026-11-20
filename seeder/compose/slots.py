"""Template slots such as `{client}`, `{contact:gen}` and `{client_iban:spaced}`.

Filling a template returns the text together with the exact span of every entity that was
put into it, which is how the evaluation sets get their labels by construction.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from seeder.companies import Company
from seeder.identifiers import spaced_iban
from seeder.names import Case, Person, article

Language = Literal["el", "en"]

_SLOT = re.compile(r"\{([a-z][a-z_0-9]*)(?::([A-Za-z_]+))?\}")
_CASES: dict[str, Case] = {"nom": "nom", "gen": "gen", "acc": "acc", "to": "acc"}
_LEGAL_FORMS_LATIN = {"Α.Ε.": "S.A.", "Ι.Κ.Ε.": "P.C.", "Ε.Π.Ε.": "Ltd"}


@dataclass(frozen=True)
class Label:
    start: int
    end: int
    type: str
    text: str
    client: str | None = None
    form: str | None = None


@dataclass(frozen=True)
class Filled:
    text: str
    labels: tuple[Label, ...]

    @property
    def entities(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(label.text for label in self.labels))


@dataclass(frozen=True)
class Mention:
    """What a slot puts into the text. `before` is an article, which stays outside the label."""

    text: str
    type: str | None = None
    client: str | None = None
    form: str | None = None
    before: str = ""


Slot = Callable[[str | None], Mention]
Slots = Mapping[str, Slot]


def plain(text: str) -> Slot:
    return lambda _: Mention(text)


def value(text: str, data_type: str, client: str | None = None) -> Slot:
    def render(modifier: str | None) -> Mention:
        shown = spaced_iban(text) if modifier == "spaced" else text
        return Mention(shown, data_type, client)

    return render


def _with_article(case_key: str, gender: Literal["m", "f"], name: str) -> str:
    word = article(_CASES[case_key.lower()], gender, name)
    if case_key.lower() == "to":
        word = f"σ{word}"
    return word.capitalize() if case_key[0].isupper() else word


def person_slot(person: Person, language: Language, client: str | None = None) -> Slot:
    """Modifiers: `nom`, `gen`, `acc`, `to` (Greek, with the article) and `latin`."""

    def render(modifier: str | None) -> Mention:
        greeklish = "greeklish" if person.greek else "exact"
        if modifier in ("latin", "alias") or (language == "en" and modifier is None):
            return Mention(person.latin, "PERSON", client, greeklish)
        if modifier in (None, "legal"):
            return Mention(person.name, "PERSON", client, "exact")
        case_key = "gen" if modifier == "gen_legal" else modifier
        name = person.inflected(_CASES[case_key.lower()])
        form = "exact" if name == person.name else "inflected"
        before = f"{_with_article(case_key, person.gender, name)} "
        return Mention(name, "PERSON", client, form, before)

    return render


def company_slot(company: Company, language: Language, client: str | None = None) -> Slot:
    """Modifiers: `legal`, `alias`, `latin`; in Greek also `nom`, `gen`, `acc`, `to`."""

    def latin_legal() -> str:
        form = company.legal_name.removeprefix(company.trade_name).strip()
        return f"{company.latin} {_LEGAL_FORMS_LATIN.get(form, form)}"

    def render(modifier: str | None) -> Mention:
        english_text = language == "en" and company.greek
        greeklish = "greeklish" if company.greek else "exact"
        if modifier == "alias":
            return Mention(company.abbreviation, "ORG", client, "alias")
        if modifier == "latin" or (english_text and modifier is None):
            return Mention(company.latin, "ORG", client, greeklish)
        if modifier is None:
            return Mention(company.trade_name, "ORG", client, "exact")
        if modifier == "legal":
            if english_text:
                return Mention(latin_legal(), "ORG", client, greeklish)
            return Mention(company.legal_name, "ORG", client, "exact")
        if modifier == "gen_legal":
            return Mention(company.legal_name, "ORG", client, "exact", "της εταιρείας ")
        case = _CASES[modifier.lower()]
        name = company.genitive if case == "gen" else company.trade_name
        form = "exact" if name == company.trade_name else "inflected"
        return Mention(name, "ORG", client, form, f"{_with_article(modifier, 'f', name)} ")

    return render


def fill(template: str, slots: Slots) -> Filled:
    parts: list[str] = []
    labels: list[Label] = []
    length = cursor = 0
    for match in _SLOT.finditer(template):
        mention = slots[match[1]](match[2])
        lead = template[cursor : match.start()] + mention.before
        parts += [lead, mention.text]
        length += len(lead)
        if mention.type:
            end = length + len(mention.text)
            labels.append(
                Label(length, end, mention.type, mention.text, mention.client, mention.form)
            )
        length += len(mention.text)
        cursor = match.end()
    parts.append(template[cursor:])
    return Filled("".join(parts), tuple(labels))


def slot_names(template: str) -> set[str]:
    return {match[1] for match in _SLOT.finditer(template)}


def join_filled(parts: Sequence[Filled], separator: str = "\n\n") -> Filled:
    """Concatenate filled texts, moving each label to its place in the whole."""
    labels: list[Label] = []
    offset = 0
    for part in parts:
        labels += [
            replace(label, start=label.start + offset, end=label.end + offset)
            for label in part.labels
        ]
        offset += len(part.text) + len(separator)
    return Filled(separator.join(part.text for part in parts), tuple(labels))
