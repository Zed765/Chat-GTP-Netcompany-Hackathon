"""The slots a template can use, built from world entities or from invented outsiders.

Facts are drawn once per document, then turned into slots for either language, so the
Greek translation of an English clause carries the same people, dates and amounts.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from seeder import identifiers
from seeder.companies import Company
from seeder.compose.slots import Language, Slot, company_slot, person_slot, plain, value
from seeder.names import Person, all_english_people, all_greek_people, person_from
from seeder.world import Client, Organisation, Project, World

MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")  # fmt: skip
MONTHS_EL = ("Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου", "Ιουλίου",
             "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου")  # fmt: skip
QUARTERS_EL = ("α΄ τρίμηνο", "β΄ τρίμηνο", "γ΄ τρίμηνο", "δ΄ τρίμηνο")


@dataclass(frozen=True)
class Party:
    """A client, or an outsider playing the part of one in a generic document."""

    name: Company | Person
    contact: Person
    afm: str
    iban: str
    email: str
    phone: str
    address: str
    contact_email: str
    contact_phone: str
    client_id: str | None = None


@dataclass(frozen=True)
class Numbers:
    day: date
    amounts: tuple[int, ...]
    rates: tuple[int, int]
    days: int
    days2: int
    months: int
    weeks: int
    years: int
    percent: int
    percent2: int
    reference: str


def company_of(client: Client) -> Company:
    greek = client.language == "el"
    return Company(
        trade_name=client.trade_name,
        legal_name=client.legal_name,
        genitive=f"{client.trade_name[:-1]}ής" if greek else client.trade_name,
        latin=client.aliases[1] if greek else client.trade_name,
        abbreviation=client.aliases[0],
        greek=greek,
    )


def client_party(client: Client, contact_index: int = 0) -> Party:
    contact = client.contacts[contact_index % len(client.contacts)]
    name = company_of(client) if client.kind == "company" else person_from(client.legal_name)
    return Party(
        name=name,
        contact=person_from(contact.name),
        afm=client.afm,
        iban=client.iban,
        email=client.email,
        phone=client.phone,
        address=client.address,
        contact_email=contact.email,
        contact_phone=contact.phone,
        client_id=client.id,
    )


def outside_party(
    rng: Random, name: Company | Person, contact: Person, language: Language
) -> Party:
    """Somebody who is not in the CRM, with identifiers of their own."""
    domain = name.domain if isinstance(name, Company) else "postbox.example"
    given, family = contact.latin.lower().split()
    city = "Αθήνα" if language == "el" else "Athens, Greece"
    street = "Οδός Αγίου Νικολάου" if language == "el" else "Agiou Nikolaou Street"
    return Party(
        name=name,
        contact=contact,
        afm=identifiers.make_afm(rng),
        iban=identifiers.make_iban(rng),
        email=f"info@{domain}" if isinstance(name, Company) else f"{given}.{family}@{domain}",
        phone=identifiers.make_landline(rng),
        address=f"{street} {rng.randrange(3, 180)}, 117 4{rng.randrange(10)} {city}",
        contact_email=f"{given[0]}.{family}@{domain}",
        contact_phone=identifiers.make_mobile(rng),
    )


def outside_people(world: World, rng: Random) -> list[Person]:
    """Everyone in the name tables who is neither an employee nor in the CRM, shuffled."""
    known = {employee.display_name for employee in world.employees}
    known |= {
        person_from(contact.name).latin for client in world.clients for contact in client.contacts
    }
    people = [p for p in all_greek_people() + all_english_people() if p.latin not in known]
    rng.shuffle(people)
    return people


def draw_numbers(rng: Random) -> Numbers:
    return Numbers(
        day=date(2026, rng.randrange(1, 11), rng.randrange(2, 28)),
        amounts=tuple(rng.randrange(18, 240) * 500 for _ in range(5)),
        rates=(rng.randrange(13, 29) * 50, rng.randrange(4, 30) * 100),
        days=rng.choice((30, 45, 60)),
        days2=rng.randrange(38, 96),
        months=rng.choice((12, 24, 36)),
        weeks=rng.choice((10, 12, 14, 16)),
        years=rng.choice((3, 5)),
        percent=rng.choice((5, 8, 10, 12)),
        percent2=rng.randrange(31, 48),
        reference=f"AD-{rng.randrange(2024, 2027)}-{rng.randrange(100, 999)}",
    )


def _money(amount: int, language: Language) -> str:
    return f"{amount:,} €".replace(",", ".") if language == "el" else f"€{amount:,}"


def _date(day: date, language: Language) -> str:
    months = MONTHS_EL if language == "el" else MONTHS_EN
    return f"{day.day} {months[day.month - 1]} {day.year}"


def number_slots(numbers: Numbers, language: Language) -> dict[str, Slot]:
    quarter = (numbers.day.month - 1) // 3
    slots = {
        "date": _date(numbers.day, language),
        "start_date": _date(numbers.day + timedelta(days=17), language),
        "end_date": _date(numbers.day + timedelta(days=17 + 7 * numbers.weeks), language),
        "rate": _money(numbers.rates[0], language),
        "rate2": _money(numbers.rates[1], language),
        "cap": _money(numbers.amounts[0] * 2, language),
        "days": str(numbers.days),
        "days2": str(numbers.days2),
        "months": str(numbers.months),
        "weeks": str(numbers.weeks),
        "years": str(numbers.years),
        "percent": str(numbers.percent),
        "percent2": str(numbers.percent2),
        "year": str(numbers.day.year),
        "quarter": QUARTERS_EL[quarter] if language == "el" else f"Q{quarter + 1}",
        "reference": numbers.reference,
    }
    names = ("amount", "amount2", "amount3", "amount4", "amount5")
    slots |= {
        name: _money(amount, language) for name, amount in zip(names, numbers.amounts, strict=True)
    }
    return {name: plain(text) for name, text in slots.items()}


def party_slots(party: Party, language: Language) -> dict[str, Slot]:
    """`client`, `contact` and the client's identifiers."""
    client_id = party.client_id
    name_slot = (
        company_slot(party.name, language, client_id)
        if isinstance(party.name, Company)
        else person_slot(party.name, language, client_id)
    )
    return {
        "client": name_slot,
        "contact": person_slot(party.contact, language, client_id),
        "client_afm": value(party.afm, "AFM", client_id),
        "client_iban": value(party.iban, "IBAN", client_id),
        "client_email": value(party.email, "EMAIL", client_id),
        "client_phone": value(party.phone, "PHONE", client_id),
        "client_address": value(party.address, "ADDRESS", client_id),
        "contact_email": value(party.contact_email, "EMAIL", client_id),
        "contact_phone": value(party.contact_phone, "PHONE", client_id),
    }


def staff_slots(lead: Person, lead2: Person, domain: str, language: Language) -> dict[str, Slot]:
    given, family = lead.latin.lower().split()
    return {
        "lead": person_slot(lead, language),
        "lead2": person_slot(lead2, language),
        "lead_email": value(f"{given[0]}.{family}@{domain}", "EMAIL"),
    }


def firm_slots(organisation: Organisation, language: Language) -> dict[str, Slot]:
    greek = language == "el"
    return {
        "org": value(organisation.name, "ORG"),
        "org_legal": value(
            organisation.legal_name if greek else organisation.legal_name_latin, "ORG"
        ),
        "org_afm": value(organisation.afm, "AFM"),
        "org_address": value(
            organisation.address if greek else organisation.address_latin, "ADDRESS"
        ),
    }


def project_slots(project: Project) -> dict[str, Slot]:
    return {
        "project": plain(project.name),
        "project_code": value(project.code, "PROJECT_CODE"),
    }


def person_slots(
    rng: Random, person: Person, person2: Person, clinic: str, language: Language
) -> dict[str, Slot]:
    """The subject of a health or HR document, with a second person such as a doctor."""
    born = identifiers.random_birth_date(rng)
    salary = rng.randrange(29, 64) * 50
    return {
        "person": person_slot(person, language),
        "person2": person_slot(person2, language),
        "amka": value(identifiers.make_amka(rng, born), "AMKA"),
        "dob": plain(_date(born, language)),
        "clinic": plain(clinic),
        "salary": plain(_money(salary, language)),
        "salary2": plain(_money(round(salary * 1.06 / 10) * 10, language)),
    }
