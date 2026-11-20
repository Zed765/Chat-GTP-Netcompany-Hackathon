"""Short prompts filled from `content/prompts.yaml`: the labelled evaluation prompts and the
seeded activity both come from here."""

import base64
from functools import cache
from random import Random

import yaml
from pydantic import BaseModel

from seeder import fake_secrets, identifiers
from seeder.companies import Company, outside_companies
from seeder.compose.context import (
    MONTHS_EL,
    MONTHS_EN,
    Party,
    client_party,
    outside_party,
    outside_people,
    party_slots,
)
from seeder.compose.library import CONTENT
from seeder.compose.slots import (
    Filled,
    Language,
    Slot,
    company_slot,
    fill,
    person_slot,
    plain,
    value,
)
from seeder.names import Person, person_from
from seeder.world import Client, World

# Which language the slots of each group of templates are written in.
SLOT_LANGUAGE: dict[str, Language] = {"en": "en", "el": "el", "greeklish": "en", "mixed": "el"}


class PromptLibrary(BaseModel):
    sensitive: dict[str, list[str]]
    benign: dict[Language, list[str]]
    topics: dict[Language, list[str]]
    marked: dict[Language, list[str]]
    markers: dict[Language, list[str]]
    secrets: dict[Language, list[str]]
    hard_negatives: dict[str, dict[Language, list[str]]]
    harmless_sentences: list[str]


@cache
def load_prompts() -> PromptLibrary:
    raw = yaml.safe_load((CONTENT / "prompts.yaml").read_text(encoding="utf-8"))
    return PromptLibrary.model_validate(raw)


def uses_company(template: str) -> bool:
    """A template that names `{client}` reads wrongly when the client is a person."""
    return "{client}" in template or "{client:" in template


class PromptFactory:
    """Fills prompt templates with clients from the CRM or with outsiders."""

    def __init__(self, world: World) -> None:
        rng = Random(f"{world.seed}:prompt-outsiders")
        self._world = world
        self._people = outside_people(world, rng)[:400]
        self._companies = outside_companies(rng)
        self._library = load_prompts()

    def client_for(self, rng: Random, template: str, team: str | None = None) -> Client:
        """A client the template suits, from the team's own accounts when it has any.

        A template that names `{client}` needs a company; the others also suit individuals.
        """
        clients = self._world.clients
        if uses_company(template):
            clients = [client for client in clients if client.kind == "company"]
        return rng.choice([client for client in clients if client.team == team] or clients)

    def about_client(self, template: str, group: str, rng: Random, client: Client) -> Filled:
        party = client_party(client, rng.randrange(len(client.contacts)))
        return self._fill(template, SLOT_LANGUAGE[group], rng, party)

    def about_outsider(self, template: str, group: str, rng: Random) -> Filled:
        """The same template about people and organisations that are not in the CRM."""
        language = SLOT_LANGUAGE[group]
        greek = language == "el" or rng.random() < 0.5
        subject, contact = rng.sample([p for p in self._people if p.greek == greek], k=2)
        name: Company | Person = subject
        if uses_company(template):
            name = rng.choice([c for c in self._companies if c.greek == greek])
        else:
            contact = subject
        return self._fill(template, language, rng, outside_party(rng, name, contact, language))

    def _fill(self, template: str, language: Language, rng: Random, party: Party) -> Filled:
        slots = self._general_slots(rng, language) | party_slots(party, language)
        return fill(template, slots)

    def _general_slots(self, rng: Random, language: Language) -> dict[str, Slot]:
        """What a prompt can mention besides the client: an outsider, a colleague, numbers."""
        person = rng.choice(self._people)
        given, family = person.latin.lower().split()
        months = MONTHS_EL if language == "el" else MONTHS_EN
        sentence = rng.choice(self._library.harmless_sentences)
        colleague = person_from(rng.choice(self._world.employees).display_name)
        slots = {
            "person": person_slot(person, language),
            "org_other": company_slot(rng.choice(self._companies), language),
            "employee": person_slot(colleague, language),
            "amka": value(identifiers.make_amka(rng), "AMKA"),
            "card": value(identifiers.make_card(rng), "CARD"),
            "id_card": value(identifiers.make_id_card(rng, current=rng.random() < 0.6), "ID_CARD"),
            "afm": value(identifiers.make_afm(rng), "AFM"),
            "iban": value(identifiers.make_iban(rng), "IBAN"),
            "email": value(f"{given}.{family}@postbox.example", "EMAIL"),
            "phone": value(identifiers.make_mobile(rng), "PHONE"),
            "project_code": value(rng.choice(self._world.projects).code, "PROJECT_CODE"),
            "marker": value(rng.choice(self._library.markers[language]), "CONFIDENTIAL_MARKER"),
            "amount": plain(f"{rng.randrange(4, 190) * 250:,} €".replace(",", ".")),
            "date": plain(f"{rng.randrange(2, 28)} {rng.choice(months)}"),
            "percent": plain(str(rng.choice((5, 8, 10, 12, 15)))),
            "order_no": plain(f"ORD-{rng.randrange(100000, 999999)}"),
            "ticket_no": plain(f"INC-{rng.randrange(100000, 999999)}"),
            "invalid_afm": plain(identifiers.make_invalid_afm(rng)),
            "topic": plain(rng.choice(self._library.topics[language])),
            "harmless_b64": plain(base64.b64encode(sentence.encode()).decode()),
        }
        secrets = {
            name: value(make(rng), "SECRET") for name, make in fake_secrets.SECRET_MAKERS.items()
        }
        return slots | secrets
