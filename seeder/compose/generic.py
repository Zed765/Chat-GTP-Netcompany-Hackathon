"""Generic documents: the default pack's exemplars and the held-out sets.

Nobody named in them is in the world: people and organisations come from the name tables
after the employees, the clients and their contacts have been taken out.
"""

from itertools import combinations
from random import Random

import yaml
from pydantic import BaseModel

from seeder.companies import Company, outside_companies
from seeder.compose.context import (
    draw_numbers,
    firm_slots,
    number_slots,
    outside_party,
    outside_people,
    party_slots,
    person_slots,
    staff_slots,
)
from seeder.compose.library import CONTENT, Document, Library, compose
from seeder.compose.slots import Language, Slot
from seeder.identifiers import make_afm
from seeder.names import Person
from seeder.world import Organisation, World


class Topic(BaseModel):
    id: str
    paragraphs: list[str]


class BenignLibrary(BaseModel):
    language: Language
    intros: list[str]
    bridges: list[str]
    closers: list[str]
    topics: list[Topic]


class Outsiders:
    """Hands out invented people and organisations that are not in the world."""

    def __init__(self, world: World, purpose: str) -> None:
        self.rng = Random(f"{world.seed}:{purpose}")
        self._people = outside_people(world, self.rng)
        self._companies = outside_companies(self.rng)
        self._next_company = 0

    def person(self, *, greek: bool) -> Person:
        index = next(i for i, person in enumerate(self._people) if person.greek == greek)
        return self._people.pop(index)

    def company(self, *, greek: bool) -> Company:
        matching = [company for company in self._companies if company.greek == greek]
        self._next_company += 1
        return matching[self._next_company % len(matching)]


def _organisation(rng: Random, company: Company, language: Language) -> Organisation:
    address = (
        f"Οδός Αγίας Παρασκευής {rng.randrange(3, 190)}, 152 3{rng.randrange(10)} Χαλάνδρι"
        if language == "el"
        else f"{rng.randrange(3, 190)} Agias Paraskevis Street, 152 3{rng.randrange(10)} Chalandri"
    )
    return Organisation(
        name=company.trade_name,
        domain=company.domain,
        legal_name=company.legal_name,
        legal_name_latin=company.legal_name,
        afm=make_afm(rng),
        address=address,
        address_latin=address,
    )


def generic_slots(outsiders: Outsiders, language: Language) -> dict[str, Slot]:
    """Every slot a generic library may use, filled with outsiders."""
    rng = outsiders.rng
    greek = language == "el"
    firm = outsiders.company(greek=greek)
    customer = outsiders.company(greek=greek)
    clinic = outsiders.company(greek=greek).trade_name.split()[0]
    party = outside_party(rng, customer, outsiders.person(greek=greek), language)
    organisation = _organisation(rng, firm, language)
    return {
        **number_slots(draw_numbers(rng), language),
        **party_slots(party, language),
        **staff_slots(
            outsiders.person(greek=greek), outsiders.person(greek=greek), firm.domain, language
        ),
        **firm_slots(organisation, language),
        **person_slots(
            rng,
            outsiders.person(greek=greek),
            outsiders.person(greek=greek),
            f"Ιατρικό Κέντρο {clinic}" if greek else f"{clinic} Medical Centre",
            language,
        ),
    }


def generic_document(
    library: Library, doc_id: str, outsiders: Outsiders, *, sections: int, title: int
) -> Document:
    slots = generic_slots(outsiders, library.language)
    return compose(library, doc_id, slots, slots, outsiders.rng, sections=sections, title=title)


def load_benign(name: str) -> BenignLibrary:
    raw = yaml.safe_load((CONTENT / f"{name}.yaml").read_text(encoding="utf-8"))
    return BenignLibrary.model_validate(raw)


def benign_documents(name: str, prefix: str, count: int, rng: Random) -> list[Document]:
    """Everyday requests: two topics in full and the opening of a third."""
    library = load_benign(name)
    triples = list(combinations(library.topics, 3))
    rng.shuffle(triples)
    documents = []
    for index, (first, second, third) in enumerate(triples[:count]):
        blocks = [
            library.intros[index % len(library.intros)],
            *first.paragraphs,
            library.bridges[index % len(library.bridges)],
            *second.paragraphs,
            library.closers[index % len(library.closers)],
            third.paragraphs[0],
        ]
        doc_id = f"{prefix}-{library.language}-{index + 1:02d}"
        documents.append(
            Document(
                id=doc_id,
                title=f"{first.id} and {second.id}",
                kind="benign",
                category="BENIGN",
                language=library.language,
                client=None,
                text="\n\n".join(block.strip() for block in blocks) + "\n",
                entities=(),
                file=f"{doc_id}.txt",
            )
        )
    return documents
