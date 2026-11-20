"""The fictional organisation behind all demo data, built from a fixed seed with no API key.

The CRM, the corpus, the seeded activity, the evaluation sets and the "Try an example"
prompts all take their entities from the `World` this module builds.
"""

import json
from pathlib import Path
from random import Random
from typing import Literal

from pydantic import BaseModel

from seeder import identifiers
from seeder.companies import (
    CLIENT_BRANDS_EL,
    CLIENT_BRANDS_EN,
    LEGAL_FORMS_EL,
    LEGAL_FORMS_EN,
    SECTORS_EL,
    SECTORS_EN,
    Company,
    english_company,
    greek_company,
)
from seeder.names import Person, all_english_people, all_greek_people, person_from

SEED = 20261114
DATA_DIR = Path(__file__).resolve().parent / "data"
TEAM_SIZES = {
    "Sales": 9,
    "Legal": 5,
    "Finance": 6,
    "Engineering": 9,
    "HR": 4,
    "Customer Support": 7,
}
DEMO_EMPLOYEE = "Eleni Papadaki"
# The analyst and the data protection officer sign in as these; no employee may share a name.
RESERVED_NAMES = frozenset({"Nikos Georgiou", "Katerina Dimitriou"})
OWNING_TEAMS = ("Sales", "Sales", "Sales", "Customer Support", "Customer Support", "Legal",
                "Finance", "Finance", "Engineering")  # fmt: skip
COMPANY_ROLES = ("Finance Director", "Procurement Manager", "Managing Director", "Legal Counsel",
                 "Operations Manager", "IT Manager", "Chief Accountant")  # fmt: skip
PROJECT_NAMES = (
    ("Helix", "HLX", "Engineering"),
    ("Meridian", "MRD", "Engineering"),
    ("Tessera", "TSR", "Engineering"),
    ("Kyma", "KYM", "Finance"),
    ("Pharos", "PHR", "Customer Support"),
    ("Argo", "ARG", "Sales"),
)
# (Greek, Latin, is an avenue)
STREETS: tuple[tuple[str, str, bool], ...] = (
    ("Ερμού", "Ermou", False), ("Σταδίου", "Stadiou", False),
    ("Πανεπιστημίου", "Panepistimiou", False), ("Ακαδημίας", "Akadimias", False),
    ("Πατησίων", "Patision", False), ("Λεωφόρος Κηφισίας", "Kifisias", True),
    ("Λεωφόρος Συγγρού", "Syngrou", True), ("Βασιλίσσης Σοφίας", "Vasilissis Sofias", False),
    ("Τσιμισκή", "Tsimiski", False), ("Εγνατία", "Egnatia", False),
    ("Ακτή Μιαούλη", "Akti Miaouli", False), ("Κορίνθου", "Korinthou", False),
    ("Μαιζώνος", "Maizonos", False), ("Ηρώων Πολυτεχνείου", "Iroon Polytechneiou", False),
)  # fmt: skip
# (Greek, Latin, postal code)
CITIES: tuple[tuple[str, str, str], ...] = (
    ("Αθήνα", "Athens", "105 63"), ("Μαρούσι", "Marousi", "151 25"),
    ("Πειραιάς", "Piraeus", "185 35"), ("Θεσσαλονίκη", "Thessaloniki", "546 24"),
    ("Πάτρα", "Patras", "262 21"), ("Ηράκλειο", "Heraklion", "712 02"),
    ("Λάρισα", "Larissa", "412 22"), ("Βόλος", "Volos", "382 21"),
    ("Χαλάνδρι", "Chalandri", "152 32"), ("Γλυφάδα", "Glyfada", "166 75"),
)  # fmt: skip

Language = Literal["el", "en"]


class Organisation(BaseModel):
    name: str
    domain: str
    legal_name: str
    legal_name_latin: str
    afm: str
    address: str
    address_latin: str


class Team(BaseModel):
    name: str
    cidr: str


class Employee(BaseModel):
    user_id: str
    display_name: str
    team: str
    ip: str


class Contact(BaseModel):
    name: str
    role: str
    email: str
    phone: str


class Client(BaseModel):
    id: str
    kind: Literal["company", "individual"]
    legal_name: str
    trade_name: str
    aliases: list[str]
    contacts: list[Contact]
    afm: str
    iban: str
    email: str
    phone: str
    address: str
    team: str
    language: Language


class Project(BaseModel):
    code: str
    name: str
    team: str


class ProjectPattern(BaseModel):
    """The organisation-specific identifier loaded as a custom T0 pattern."""

    name: str
    regex: str
    data_type: str


class World(BaseModel):
    seed: int
    organisation: Organisation
    teams: list[Team]
    employees: list[Employee]
    clients: list[Client]
    projects: list[Project]
    project_pattern: ProjectPattern

    def client(self, client_id: str) -> Client:
        return next(client for client in self.clients if client.id == client_id)

    @property
    def scene_client(self) -> Client:
        """The client of demo scene 1; the same one appears in the CRM, a contract and the sets."""
        return self.clients[0]


class _People:
    """Hands out people so that nobody appears twice in the world."""

    def __init__(self, rng: Random) -> None:
        self._rng = rng
        self._greek = all_greek_people()
        self._english = all_english_people()
        rng.shuffle(self._greek)
        rng.shuffle(self._english)
        self._used = set(RESERVED_NAMES)

    def take(self, name: str) -> Person:
        person = person_from(name)
        self._used.add(person.latin)
        return person

    def next(self, *, greek: bool = True) -> Person:
        pool = self._greek if greek else self._english
        while True:
            person = pool.pop()
            if person.latin not in self._used:
                self._used.add(person.latin)
                return person


def _user_id(person: Person) -> str:
    given, family = person.latin.split()
    return f"{given[0]}.{family}".lower()


def _address(rng: Random, language: Language) -> str:
    street, street_latin, avenue = rng.choice(STREETS)
    city, city_latin, postal_code = rng.choice(CITIES)
    number = rng.randrange(2, 240)
    if language == "el":
        return f"{street} {number}, {postal_code} {city}"
    kind = "Avenue" if avenue else "Street"
    return f"{number} {street_latin} {kind}, {postal_code} {city_latin}, Greece"


def _employees(rng: Random, people: _People, teams: list[Team]) -> list[Employee]:
    employees: list[Employee] = []
    taken = {_user_id(person_from(name)) for name in RESERVED_NAMES}
    for team in teams:
        prefix = team.cidr.rsplit(".", 1)[0]
        for seat in range(TEAM_SIZES[team.name]):
            first_in_sales = team.name == "Sales" and seat == 0
            person = people.take(DEMO_EMPLOYEE) if first_in_sales else people.next()
            while _user_id(person) in taken:
                person = people.next()
            taken.add(_user_id(person))
            employees.append(
                Employee(
                    user_id=_user_id(person),
                    display_name=person.latin,
                    team=team.name,
                    ip=f"{prefix}.{11 + seat}",
                )
            )
    return employees


def _contact(person: Person, role: str, domain: str, rng: Random, *, greek_script: bool) -> Contact:
    given, family = person.latin.lower().split()
    return Contact(
        name=person.name if greek_script else person.latin,
        role=role,
        email=f"{given[0]}.{family}@{domain}",
        phone=identifiers.make_mobile(rng),
    )


def _company_client(
    rng: Random, people: _People, company: Company, first_contact: Person | None, team: str
) -> Client:
    roles = rng.sample(COMPANY_ROLES, k=rng.choice((1, 2, 2, 3)))
    persons = [first_contact or people.next(greek=company.greek)]
    persons += [people.next(greek=company.greek) for _ in roles[1:]]
    language: Language = "el" if company.greek else "en"
    aliases = [company.abbreviation, company.latin] if company.greek else [company.abbreviation]
    return Client(
        id="",
        kind="company",
        legal_name=company.legal_name,
        trade_name=company.trade_name,
        aliases=aliases,
        contacts=[
            _contact(person, role, company.domain, rng, greek_script=company.greek)
            for person, role in zip(persons, roles, strict=True)
        ],
        afm=identifiers.make_afm(rng),
        iban=identifiers.make_iban(rng),
        email=f"info@{company.domain}",
        phone=identifiers.make_landline(rng),
        address=_address(rng, language),
        team=team,
        language=language,
    )


def _individual_client(rng: Random, people: _People, *, greek: bool, team: str) -> Client:
    person = people.next(greek=greek)
    contacts = [_contact(person, "Account holder", "mailbox.example", rng, greek_script=greek)]
    if rng.random() < 0.35:
        adviser = people.next(greek=greek)
        contacts.append(
            _contact(adviser, "Accountant", "logistis.example", rng, greek_script=greek)
        )
    language: Language = "el" if greek else "en"
    return Client(
        id="",
        kind="individual",
        legal_name=person.name,
        trade_name=person.name,
        aliases=[person.latin] if greek else [],
        contacts=contacts,
        afm=identifiers.make_afm(rng),
        iban=identifiers.make_iban(rng),
        email=contacts[0].email,
        phone=contacts[0].phone,
        address=_address(rng, language),
        team=team,
        language=language,
    )


def _clients(rng: Random, people: _People) -> list[Client]:
    sectors_el = rng.sample(SECTORS_EL, k=len(SECTORS_EL))
    greek = [
        greek_company(brand, sectors_el[index % len(sectors_el)], rng.choice(LEGAL_FORMS_EL))
        for index, brand in enumerate(CLIENT_BRANDS_EL)
    ]
    sectors_en = rng.sample(SECTORS_EN, k=len(SECTORS_EN))
    english = [
        english_company(brand, sectors_en[index], rng.choice(LEGAL_FORMS_EN))
        for index, brand in enumerate(CLIENT_BRANDS_EN)
    ]
    scene_company, others = greek[0], greek[1:] + english
    rng.shuffle(others)
    clients = [
        _company_client(rng, people, scene_company, people.take("Μαρία Παπαδοπούλου"), "Sales")
    ]
    clients += [
        _company_client(rng, people, company, None, rng.choice(OWNING_TEAMS)) for company in others
    ]
    clients += [
        _individual_client(rng, people, greek=index % 10 < 7, team=rng.choice(OWNING_TEAMS))
        for index in range(20)
    ]
    return [
        client.model_copy(update={"id": f"C{number:03d}"})
        for number, client in enumerate(clients, 1)
    ]


def build_world(seed: int = SEED) -> World:
    rng = Random(seed)
    people = _People(rng)
    teams = [
        Team(name=name, cidr=f"10.20.{number}.0/24") for number, name in enumerate(TEAM_SIZES, 1)
    ]
    organisation = Organisation(
        name="Aspida Demo Consulting",
        domain="aspida-demo.example",
        legal_name="Aspida Demo Consulting Μονοπρόσωπη Α.Ε.",
        legal_name_latin="Aspida Demo Consulting Single Member S.A.",
        afm=identifiers.make_afm(rng),
        address="Λεωφόρος Μεσογείων 310, 155 62 Χολαργός",
        address_latin="310 Mesogeion Avenue, 155 62 Cholargos, Greece",
    )
    employees = _employees(rng, people, teams)
    clients = _clients(rng, people)
    projects = [
        Project(code=f"PRJ-{short}-{rng.randrange(1000, 9999)}", name=name, team=team)
        for name, short, team in PROJECT_NAMES
    ]
    pattern = ProjectPattern(
        name="Project code", regex=r"\bPRJ-[A-Z]{3}-[0-9]{4}\b", data_type="PROJECT_CODE"
    )
    return World(
        seed=seed,
        organisation=organisation,
        teams=teams,
        employees=employees,
        clients=clients,
        projects=projects,
        project_pattern=pattern,
    )


def load_world(data_dir: Path = DATA_DIR) -> World:
    return World.model_validate_json((data_dir / "world.json").read_text(encoding="utf-8"))


def write_world(world: World, data_dir: Path = DATA_DIR) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "world.json").write_text(
        json.dumps(world.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    clients = [client.model_dump() for client in world.clients]
    (data_dir / "clients.json").write_text(
        json.dumps(clients, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
