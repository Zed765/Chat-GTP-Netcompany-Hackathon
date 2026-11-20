"""Greek company names the language models do not recognise.

Greek firms are commonly named with a brand followed by their sector as an adjective:
"Ήλιος Ναυτιλιακή", "Αττική Ασφαλιστική", or in Latin letters "Ilios Naftiliaki". The small
models read such a pair as a person or miss it, so the convention is matched directly.
"""

from collections.abc import Iterator, Sequence
from itertools import pairwise

from gateway.app.core.textnorm import fold, latin_key
from gateway.app.core.types import DataType, Tier
from gateway.app.detect.spans import Span
from gateway.app.detect.tokens import Token, name_key

SECTOR_SCORE = 0.9
SECTOR_RECOGNISER = "org:sector"
MIN_BRAND_LETTERS = 3

_SECTOR_ADJECTIVES = (
    "Ναυτιλιακή", "Ακτοπλοϊκή", "Αεροπορική", "Μεταφορική", "Εμπορική", "Εισαγωγική",
    "Εξαγωγική", "Βιομηχανική", "Βιοτεχνική", "Τεχνική", "Κατασκευαστική", "Οικοδομική",
    "Δομική", "Κτηματική", "Μεσιτική", "Ασφαλιστική", "Τραπεζική", "Επενδυτική",
    "Χρηματιστηριακή", "Χρηματοδοτική", "Λογιστική", "Συμβουλευτική", "Ενεργειακή",
    "Ηλεκτρική", "Ηλεκτρονική", "Πληροφορική", "Τηλεπικοινωνιακή", "Ψηφιακή", "Μηχανική",
    "Χημική", "Φαρμακευτική", "Ιατρική", "Διαγνωστική", "Τουριστική", "Ξενοδοχειακή",
    "Εκδοτική", "Διαφημιστική", "Εκπαιδευτική", "Αγροτική", "Γεωργική", "Κτηνοτροφική",
    "Αλιευτική", "Μεταλλευτική", "Οινοποιητική", "Αναπτυξιακή", "Διαχειριστική",
    "Εφοδιαστική", "Αποθηκευτική", "Κλωστοϋφαντουργική", "Τροφοδοτική",
)  # fmt: skip
# The nominative and the genitive, in the spelling-tolerant key Greek and Greeklish share.
_SECTORS = frozenset(latin_key(form) for word in _SECTOR_ADJECTIVES for form in (word, f"{word}ς"))
# Words that start a sentence before a sector adjective without being a brand.
_NOT_A_BRAND = frozenset(
    fold(word)
    for word in (
        "Της", "Την", "Στην", "Στη", "Από", "Για", "Μια", "Και", "Νέα", "Γενική", "Εφαρμοσμένη",
        "The", "Our", "Their", "This", "That", "With", "From", "For", "And",
    )
)  # fmt: skip


# A department or a job title is neither a company nor a person.
UNIT_WORDS = frozenset(
    fold(word)
    for word in (
        "Customer", "Customers", "Support", "Service", "Services", "Sales", "Finance", "Legal",
        "Engineering", "Marketing", "Operations", "Procurement", "Accounting", "Compliance",
        "Security", "Human", "Resources", "Team", "Department", "Office", "Desk", "Helpdesk",
        "Management", "Manager", "Director", "Officer", "Board", "Committee", "Account",
        "Relations", "Research", "Development", "Quality", "Logistics", "Payroll", "Audit",
        "Τμήμα", "Διεύθυνση", "Υπηρεσία", "Πωλήσεις", "Πωλήσεων", "Υποστήριξη", "Υποστήριξης",
        "Εξυπηρέτηση", "Εξυπηρέτησης", "Πελατών", "Λογιστήριο", "Προμήθειες", "Προμηθειών",
        "Προσωπικού", "Ομάδα", "Γραφείο", "Διευθυντής", "Διευθύντρια", "Υπεύθυνος", "Υπεύθυνη",
    )
)  # fmt: skip


def is_unit_word(token: Token) -> bool:
    return fold(token.text) in UNIT_WORDS


def is_sector(token: Token) -> bool:
    return token.capitalised and name_key(token.text) in _SECTORS


def find_companies(text: str, tokens: Sequence[Token]) -> Iterator[Span]:
    """A capitalised brand word directly followed by a capitalised sector adjective."""
    for brand, sector in pairwise(tokens):
        if (
            is_sector(sector)
            and brand.capitalised
            and len(brand.text) >= MIN_BRAND_LETTERS
            and text[brand.end : sector.start] == " "
            and fold(brand.text) not in _NOT_A_BRAND
            and not is_sector(brand)
            and not is_unit_word(brand)
        ):
            yield Span(
                DataType.ORG, brand.start, sector.end, Tier.T1, SECTOR_SCORE, SECTOR_RECOGNISER
            )
