"""Name tables for the fictional world, with Greek inflection and Latin spellings.

World files hold plain strings. `person_from` turns such a string back into a `Person`, so
documents and datasets can use the genitive ("της Μαρίας Παπαδοπούλου") or the Latin
spelling ("Maria Papadopoulou") of the same person.
"""

from dataclasses import dataclass
from typing import Literal

Gender = Literal["m", "f"]
Case = Literal["nom", "gen", "acc"]

# (Greek, Latin)
MALE_GIVEN: tuple[tuple[str, str], ...] = (
    ("Γιώργος", "Giorgos"), ("Νίκος", "Nikos"), ("Γιάννης", "Giannis"),
    ("Δημήτρης", "Dimitris"), ("Κώστας", "Kostas"), ("Βασίλης", "Vasilis"),
    ("Χρήστος", "Christos"), ("Παναγιώτης", "Panagiotis"), ("Θανάσης", "Thanasis"),
    ("Μιχάλης", "Michalis"), ("Αντώνης", "Antonis"), ("Σπύρος", "Spyros"),
    ("Στέλιος", "Stelios"), ("Πέτρος", "Petros"), ("Ανδρέας", "Andreas"),
    ("Αλέξανδρος", "Alexandros"), ("Σταύρος", "Stavros"), ("Μανώλης", "Manolis"),
    ("Θοδωρής", "Thodoris"), ("Λευτέρης", "Lefteris"), ("Άρης", "Aris"),
    ("Τάσος", "Tasos"), ("Ηλίας", "Ilias"), ("Παύλος", "Pavlos"),
    ("Φώτης", "Fotis"), ("Στέφανος", "Stefanos"),
)  # fmt: skip
FEMALE_GIVEN: tuple[tuple[str, str], ...] = (
    ("Μαρία", "Maria"), ("Ελένη", "Eleni"), ("Κατερίνα", "Katerina"),
    ("Σοφία", "Sofia"), ("Άννα", "Anna"), ("Δήμητρα", "Dimitra"),
    ("Ιωάννα", "Ioanna"), ("Χριστίνα", "Christina"), ("Βασιλική", "Vasiliki"),
    ("Αγγελική", "Angeliki"), ("Ειρήνη", "Eirini"), ("Γεωργία", "Georgia"),
    ("Αθηνά", "Athina"), ("Ευαγγελία", "Evangelia"), ("Κωνσταντίνα", "Konstantina"),
    ("Αναστασία", "Anastasia"), ("Παναγιώτα", "Panagiota"), ("Δέσποινα", "Despoina"),
    ("Φωτεινή", "Foteini"), ("Ζωή", "Zoi"), ("Νίκη", "Niki"),
    ("Χαρά", "Chara"), ("Στέλλα", "Stella"), ("Ξένια", "Xenia"),
    ("Όλγα", "Olga"), ("Θεοδώρα", "Theodora"),
)  # fmt: skip
# (male Greek, female Greek, male Latin, female Latin)
SURNAMES: tuple[tuple[str, str, str, str], ...] = (
    ("Παπαδόπουλος", "Παπαδοπούλου", "Papadopoulos", "Papadopoulou"),
    ("Παπαδάκης", "Παπαδάκη", "Papadakis", "Papadaki"),
    ("Γεωργίου", "Γεωργίου", "Georgiou", "Georgiou"),
    ("Δημητρίου", "Δημητρίου", "Dimitriou", "Dimitriou"),
    ("Νικολάου", "Νικολάου", "Nikolaou", "Nikolaou"),
    ("Ιωάννου", "Ιωάννου", "Ioannou", "Ioannou"),
    ("Οικονόμου", "Οικονόμου", "Oikonomou", "Oikonomou"),
    ("Αθανασίου", "Αθανασίου", "Athanasiou", "Athanasiou"),
    ("Κωνσταντίνου", "Κωνσταντίνου", "Konstantinou", "Konstantinou"),
    ("Αναστασίου", "Αναστασίου", "Anastasiou", "Anastasiou"),
    ("Βασιλείου", "Βασιλείου", "Vasileiou", "Vasileiou"),
    ("Χριστοδούλου", "Χριστοδούλου", "Christodoulou", "Christodoulou"),
    ("Καραγιάννης", "Καραγιάννη", "Karagiannis", "Karagianni"),
    ("Αντωνιάδης", "Αντωνιάδου", "Antoniadis", "Antoniadou"),
    ("Μαυρίδης", "Μαυρίδου", "Mavridis", "Mavridou"),
    ("Γεωργιάδης", "Γεωργιάδου", "Georgiadis", "Georgiadou"),
    ("Παυλίδης", "Παυλίδου", "Pavlidis", "Pavlidou"),
    ("Ιωαννίδης", "Ιωαννίδου", "Ioannidis", "Ioannidou"),
    ("Κυριακίδης", "Κυριακίδου", "Kyriakidis", "Kyriakidou"),
    ("Στεφανίδης", "Στεφανίδου", "Stefanidis", "Stefanidou"),
    ("Αλεξίου", "Αλεξίου", "Alexiou", "Alexiou"),
    ("Μακρής", "Μακρή", "Makris", "Makri"),
    ("Κόκκινος", "Κόκκινου", "Kokkinos", "Kokkinou"),
    ("Ζερβός", "Ζερβού", "Zervos", "Zervou"),
    ("Λαμπράκης", "Λαμπράκη", "Lamprakis", "Lampraki"),
    ("Τζανετάκης", "Τζανετάκη", "Tzanetakis", "Tzanetaki"),
    ("Σταματόπουλος", "Σταματοπούλου", "Stamatopoulos", "Stamatopoulou"),
    ("Δημόπουλος", "Δημοπούλου", "Dimopoulos", "Dimopoulou"),
    ("Νικολόπουλος", "Νικολοπούλου", "Nikolopoulos", "Nikolopoulou"),
    ("Θεοδωρόπουλος", "Θεοδωροπούλου", "Theodoropoulos", "Theodoropoulou"),
    ("Κωστόπουλος", "Κωστοπούλου", "Kostopoulos", "Kostopoulou"),
    ("Γιαννόπουλος", "Γιαννοπούλου", "Giannopoulos", "Giannopoulou"),
    ("Χατζής", "Χατζή", "Chatzis", "Chatzi"),
    ("Βλάχος", "Βλάχου", "Vlachos", "Vlachou"),
    ("Κατσαρός", "Κατσαρού", "Katsaros", "Katsarou"),
    ("Λιάπης", "Λιάπη", "Liapis", "Liapi"),
    ("Μπακάλης", "Μπακάλη", "Bakalis", "Bakali"),
    ("Ντόκος", "Ντόκου", "Dokos", "Dokou"),
    ("Γκίκας", "Γκίκα", "Gkikas", "Gkika"),
    ("Ρήγας", "Ρήγα", "Rigas", "Riga"),
    ("Σιδέρης", "Σιδέρη", "Sideris", "Sideri"),
    ("Τσολάκης", "Τσολάκη", "Tsolakis", "Tsolaki"),
    ("Φωτίου", "Φωτίου", "Fotiou", "Fotiou"),
    ("Ξυδάκης", "Ξυδάκη", "Xydakis", "Xydaki"),
    ("Ψαρράς", "Ψαρρά", "Psarras", "Psarra"),
    ("Καλογεράκης", "Καλογεράκη", "Kalogerakis", "Kalogeraki"),
    ("Μαργαρίτης", "Μαργαρίτη", "Margaritis", "Margariti"),
    ("Πολίτης", "Πολίτη", "Politis", "Politi"),
    ("Σαββίδης", "Σαββίδου", "Savvidis", "Savvidou"),
    ("Τριανταφύλλου", "Τριανταφύλλου", "Triantafyllou", "Triantafyllou"),
    ("Βενιέρης", "Βενιέρη", "Venieris", "Venieri"),
    ("Δρόσος", "Δρόσου", "Drosos", "Drosou"),
    ("Κουρής", "Κουρή", "Kouris", "Kouri"),
    ("Λάμπρου", "Λάμπρου", "Lamprou", "Lamprou"),
    ("Μελετίου", "Μελετίου", "Meletiou", "Meletiou"),
    ("Σπανός", "Σπανού", "Spanos", "Spanou"),
)
ENGLISH_MALE = ("James", "Oliver", "Henry", "Thomas", "Daniel", "Samuel", "Edward", "Marcus")
ENGLISH_FEMALE = ("Emma", "Charlotte", "Alice", "Hannah", "Laura", "Sarah", "Julia", "Claire")
ENGLISH_SURNAMES = (
    "Whitfield", "Harrow", "Ashdown", "Pemberton", "Lindqvist", "Brandt", "Keller", "Moreau",
    "Castellan", "Thornbury", "Wexford", "Aldridge", "Fairbanks", "Hollis", "Marlowe", "Renshaw",
)  # fmt: skip

_ARTICLES: dict[Case, dict[Gender, str]] = {
    "nom": {"m": "ο", "f": "η"},
    "gen": {"m": "του", "f": "της"},
    "acc": {"m": "τον", "f": "την"},
}
# The feminine accusative article keeps its final ν only before these sounds.
_KEEPS_NU = ("κ", "π", "τ", "ξ", "ψ", "μπ", "ντ", "γκ", "τσ", "τζ")
_VOWELS = "αεηιουωάέήίόύώ"


def _decline_male(word: str, case: Case) -> str:
    if case == "nom":
        return word
    if word.endswith("ος"):
        return word[:-2] + ("ου" if case == "gen" else "ο")
    if word.endswith("ός"):
        return word[:-2] + ("ού" if case == "gen" else "ό")
    if word[-1] == "ς":
        return word[:-1]
    return word


def _decline_female_given(word: str, case: Case) -> str:
    return f"{word}ς" if case == "gen" else word


def article(case: Case, gender: Gender, next_word: str) -> str:
    """The definite article that goes before `next_word`."""
    form = _ARTICLES[case][gender]
    if case == "acc" and gender == "f":
        start = next_word.casefold()
        if not (start[0] in _VOWELS or start.startswith(_KEEPS_NU)):
            return "τη"
    return form


@dataclass(frozen=True)
class Person:
    given: str
    family: str
    gender: Gender
    latin: str
    greek: bool

    @property
    def name(self) -> str:
        return f"{self.given} {self.family}"

    def inflected(self, case: Case) -> str:
        """The name in a Greek case. Non-Greek names and female surnames do not change."""
        if not self.greek or case == "nom":
            return self.name
        if self.gender == "m":
            return f"{_decline_male(self.given, case)} {_decline_male(self.family, case)}"
        return f"{_decline_female_given(self.given, case)} {self.family}"


def greek_person(given_index: int, surname_index: int, gender: Gender) -> Person:
    given, given_latin = (MALE_GIVEN if gender == "m" else FEMALE_GIVEN)[given_index]
    male, female, male_latin, female_latin = SURNAMES[surname_index]
    family, family_latin = (male, male_latin) if gender == "m" else (female, female_latin)
    return Person(given, family, gender, f"{given_latin} {family_latin}", greek=True)


def english_person(given: str, family: str, gender: Gender) -> Person:
    return Person(given, family, gender, f"{given} {family}", greek=False)


def all_greek_people() -> list[Person]:
    tables: tuple[tuple[Gender, int], ...] = (("m", len(MALE_GIVEN)), ("f", len(FEMALE_GIVEN)))
    return [
        greek_person(given, surname, gender)
        for gender, count in tables
        for given in range(count)
        for surname in range(len(SURNAMES))
    ]


def all_english_people() -> list[Person]:
    tables: tuple[tuple[Gender, tuple[str, ...]], ...] = (
        ("m", ENGLISH_MALE),
        ("f", ENGLISH_FEMALE),
    )
    return [
        english_person(given, family, gender)
        for gender, givens in tables
        for given in givens
        for family in ENGLISH_SURNAMES
    ]


def _index() -> dict[str, Person]:
    people = {person.latin: person for person in all_greek_people() + all_english_people()}
    people.update({person.name: person for person in all_greek_people()})
    return people


_PEOPLE = _index()


def person_from(name: str) -> Person:
    """The `Person` behind a name written in Greek or in Latin characters."""
    return _PEOPLE[name]
