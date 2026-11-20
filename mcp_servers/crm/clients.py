"""The mock CRM's records: the seeded client file when it exists, otherwise a small fixture."""

import json
import unicodedata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CLIENTS_FILE = Path(__file__).resolve().parents[2] / "seeder" / "data" / "clients.json"

# Invented names and `.example` domains; the AFMs and IBANs pass their checksums.
FIXTURE: list[dict[str, Any]] = [
    {
        "id": "C-0001",
        "kind": "company",
        "legal_name": "Ήλιος Ναυτιλιακή Α.Ε.",
        "trade_name": "Helios Shipping",
        "aliases": ["ΗΛΝΑ", "Ilios Naftiliaki"],
        "contacts": [
            {
                "name": "Μαρία Παπαδοπούλου",
                "role": "Οικονομική Διευθύντρια",
                "email": "m.papadopoulou@helios-shipping.example",
                "phone": "+30 210 555 0141",
            }
        ],
        "afm": "138978270",
        "iban": "GR5307362069866433728935367",
        "email": "info@helios-shipping.example",
        "phone": "+30 210 555 0140",
        "address": "Ακτή Μιαούλη 85, 185 38 Πειραιάς",
        "team": "Sales",
        "language": "el",
    },
    {
        "id": "C-0002",
        "kind": "company",
        "legal_name": "Aegean Olive Cooperative",
        "trade_name": "Aegean Olive",
        "aliases": ["AOC"],
        "contacts": [
            {
                "name": "Nikos Stavrou",
                "role": "Export Manager",
                "email": "n.stavrou@aegean-olive.example",
                "phone": "+30 2810 555 0172",
            },
            {
                "name": "Eleni Vasilaki",
                "role": "Accountant",
                "email": "e.vasilaki@aegean-olive.example",
                "phone": "+30 2810 555 0173",
            },
        ],
        "afm": "412952760",
        "iban": "GR7729132158252742264232026",
        "email": "office@aegean-olive.example",
        "phone": "+30 2810 555 0170",
        "address": "25is Avgoustou 12, 712 02 Heraklion",
        "team": "Sales",
        "language": "en",
    },
    {
        "id": "C-0003",
        "kind": "company",
        "legal_name": "Θεσσαλική Ενεργειακή Μ.Ι.Κ.Ε.",
        "trade_name": "Thessaly Energy",
        "aliases": ["ΘΕΝ", "Thessaliki Energeiaki"],
        "contacts": [
            {
                "name": "Γιώργος Καραγιάννης",
                "role": "Νομικός Σύμβουλος",
                "email": "g.karagiannis@thessaly-energy.example",
                "phone": "+30 2410 555 0118",
            }
        ],
        "afm": "786569254",
        "iban": "GR8795958377257187378543997",
        "email": "contact@thessaly-energy.example",
        "phone": "+30 2410 555 0117",
        "address": "Παπαναστασίου 44, 412 22 Λάρισα",
        "team": "Legal",
        "language": "el",
    },
    {
        "id": "C-0004",
        "kind": "company",
        "legal_name": "Northwind Logistics Ltd",
        "trade_name": "Northwind",
        "aliases": ["NWL"],
        "contacts": [
            {
                "name": "Sophia Mitchell",
                "role": "Finance Lead",
                "email": "s.mitchell@northwind-logistics.example",
                "phone": "+30 2310 555 0193",
            }
        ],
        "afm": "793065367",
        "iban": "GR2062848552016276113728328",
        "email": "accounts@northwind-logistics.example",
        "phone": "+30 2310 555 0190",
        "address": "Monastiriou 60, 546 27 Thessaloniki",
        "team": "Finance",
        "language": "en",
    },
    {
        "id": "C-0005",
        "kind": "individual",
        "legal_name": "Δημήτρης Αλεξίου",
        "trade_name": "",
        "aliases": ["Dimitris Alexiou"],
        "contacts": [
            {
                "name": "Δημήτρης Αλεξίου",
                "role": "Ο ίδιος",
                "email": "d.alexiou@mail-alexiou.example",
                "phone": "+30 694 555 0126",
            }
        ],
        "afm": "944710049",
        "iban": "GR5851752024017747489163545",
        "email": "d.alexiou@mail-alexiou.example",
        "phone": "+30 694 555 0126",
        "address": "Κορίνθου 210, 262 23 Πάτρα",
        "team": "Customer Support",
        "language": "el",
    },
    {
        "id": "C-0006",
        "kind": "individual",
        "legal_name": "Katerina Markou",
        "trade_name": "",
        "aliases": ["Κατερίνα Μάρκου"],
        "contacts": [
            {
                "name": "Katerina Markou",
                "role": "Self",
                "email": "k.markou@markou-design.example",
                "phone": "+30 697 555 0158",
            }
        ],
        "afm": "048098442",
        "iban": "GR7422262943160094340446802",
        "email": "k.markou@markou-design.example",
        "phone": "+30 697 555 0158",
        "address": "Ermou 18, 105 63 Athens",
        "team": "Sales",
        "language": "en",
    },
]


class Contact(BaseModel):
    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None


class ClientRecord(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: str
    kind: str = "company"
    legal_name: str
    trade_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    afm: str | None = None
    iban: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    team: str | None = None

    @property
    def display_name(self) -> str:
        if self.trade_name and self.trade_name != self.legal_name:
            return f"{self.legal_name} ({self.trade_name})"
        return self.legal_name


def fold(text: str) -> str:
    """Lower-case and strip accents, so a search for "ηλιος" finds "Ήλιος"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _haystack(client: ClientRecord) -> str:
    parts = [
        client.id,
        client.legal_name,
        client.trade_name,
        client.afm,
        client.email,
        client.team,
        *client.aliases,
        *(contact.name for contact in client.contacts),
    ]
    return fold(" ".join(part for part in parts if part))


class ClientDirectory:
    def __init__(self, raw: list[dict[str, Any]]) -> None:
        self.raw = raw
        self.clients = [ClientRecord.model_validate(entry) for entry in raw]
        self.notes: dict[str, list[str]] = {}
        self._haystacks = {client.id: _haystack(client) for client in self.clients}

    @classmethod
    def load(cls, path: Path = CLIENTS_FILE) -> "ClientDirectory":
        if path.exists():
            return cls(json.loads(path.read_text(encoding="utf-8")))
        return cls(FIXTURE)

    def get(self, client_id: str) -> ClientRecord | None:
        wanted = client_id.strip().casefold()
        return next((c for c in self.clients if c.id.casefold() == wanted), None)

    def search(self, query: str) -> list[ClientRecord]:
        """Clients matching every word of the query, or failing that, the most words."""
        words = fold(query).split()
        if not words:
            return list(self.clients)
        scored = [
            (sum(word in self._haystacks[client.id] for word in words), client)
            for client in self.clients
        ]
        best = max((score for score, _ in scored), default=0)
        return [client for score, client in scored if score == best and best > 0]

    def add_note(self, client_id: str, note: str) -> ClientRecord | None:
        client = self.get(client_id)
        if client is not None:
            self.notes.setdefault(client.id, []).append(note)
        return client
