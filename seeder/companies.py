"""Invented company names. Client names and outside names come from separate tables, so a
dataset can name an organisation that is certainly not a client."""

import unicodedata
from dataclasses import dataclass
from random import Random

# (Greek, Latin)
CLIENT_BRANDS_EL: tuple[tuple[str, str], ...] = (
    ("Αστρολίθι", "Astrolithi"), ("Κυματώ", "Kymato"), ("Θαλασσόλιθος", "Thalassolithos"),
    ("Ανεμόεσσα", "Anemoessa"), ("Μελισσώνας", "Melissonas"), ("Πετροκάραβο", "Petrokaravo"),
    ("Λιόφυτο", "Liofyto"), ("Χρυσόκλαδο", "Chrysoklado"), ("Αμπελοφόρος", "Ampeloforos"),
    ("Κρινάνθεμο", "Krinanthemo"), ("Γλαυκόπετρα", "Glafkopetra"), ("Ηλιόδεντρο", "Iliodentro"),
    ("Κεδρόφυλλο", "Kedrofyllo"), ("Δρυόκαστρο", "Dryokastro"), ("Σταχυόμυλος", "Stachyomylos"),
    ("Νεφελοβάτης", "Nefelovatis"), ("Βραχόνησος", "Vrachonisos"), ("Αργυρόνερο", "Argyronero"),
    ("Καστανόλοφος", "Kastanolofos"), ("Μαρμαρόκτιστο", "Marmaroktisto"),
    ("Ανθόκηπος", "Anthokipos"), ("Ασημόπετρα", "Asimopetra"), ("Περιστερώνας", "Peristeronas"),
    ("Φεγγαρόλουστο", "Fengaroloussto"), ("Κυπαρισσώνας", "Kyparissonas"),
    ("Αλατόπετρα", "Alatopetra"),
)  # fmt: skip
OUTSIDE_BRANDS_EL: tuple[tuple[str, str], ...] = (
    ("Ροδόκηπος", "Rodokipos"), ("Λιθόστρωτο", "Lithostroto"), ("Ανεμόμυλος", "Anemomylos"),
    ("Κοχυλόπετρα", "Kochylopetra"), ("Ελαιόδασος", "Elaiodasos"),
    ("Χιονόβραχος", "Chionovrachos"), ("Αστερόκαμπος", "Asterokampos"),
    ("Μυρτόφυλλο", "Myrtofyllo"), ("Πευκόλοφος", "Pefkolofos"), ("Δαφνόκλαδο", "Dafnoklado"),
    ("Κρυσταλλόνερο", "Krystallonero"), ("Σιταρόκαμπος", "Sitarokampos"),
)  # fmt: skip
CLIENT_BRANDS_EN = (
    "Brackenmoor", "Tidewell", "Quillhaven", "Ferncastle", "Wrenfield", "Copperline", "Lumenridge",
    "Oakhollow", "Thistledown", "Emberfield", "Corvane", "Velmont", "Kestrelby", "Halewick",
)  # fmt: skip
OUTSIDE_BRANDS_EN = (
    "Marrowgate", "Pinecroft", "Saltwick", "Hollowmere", "Dunbarrow", "Larkspire", "Ironvale",
    "Greymantle", "Foxhollow", "Ashcombe", "Wintermoor", "Stonelea",
)  # fmt: skip
# (Greek nominative, Greek genitive, Latin)
SECTORS_EL: tuple[tuple[str, str, str], ...] = (
    ("Ναυτιλιακή", "Ναυτιλιακής", "Naftiliaki"), ("Τεχνική", "Τεχνικής", "Techniki"),
    ("Εμπορική", "Εμπορικής", "Emporiki"),
    ("Κατασκευαστική", "Κατασκευαστικής", "Kataskevastiki"),
    ("Ενεργειακή", "Ενεργειακής", "Energeiaki"), ("Ασφαλιστική", "Ασφαλιστικής", "Asfalistiki"),
    ("Τουριστική", "Τουριστικής", "Touristiki"), ("Αγροτική", "Αγροτικής", "Agrotiki"),
    ("Φαρμακευτική", "Φαρμακευτικής", "Farmakeftiki"),
    ("Μεταφορική", "Μεταφορικής", "Metaforiki"),
    ("Ξενοδοχειακή", "Ξενοδοχειακής", "Xenodocheiaki"), ("Εκδοτική", "Εκδοτικής", "Ekdotiki"),
    ("Βιομηχανική", "Βιομηχανικής", "Viomichaniki"), ("Πληροφορική", "Πληροφορικής", "Pliroforiki"),
)  # fmt: skip
SECTORS_EN = (
    "Shipping", "Logistics", "Capital", "Pharma", "Energy", "Hospitality", "Foods", "Systems",
    "Insurance", "Media", "Engineering", "Trading", "Biotech", "Retail",
)  # fmt: skip
LEGAL_FORMS_EL = ("Α.Ε.", "Ι.Κ.Ε.", "Ε.Π.Ε.", "Α.Ε.")
LEGAL_FORMS_EN = ("Ltd", "LLC", "GmbH", "S.A.", "B.V.", "Inc.")


@dataclass(frozen=True)
class Company:
    trade_name: str
    legal_name: str
    genitive: str
    latin: str
    abbreviation: str
    greek: bool

    @property
    def domain(self) -> str:
        return f"{self.latin.split()[0].lower()}.example"


def _initials(trade_name: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFD", trade_name) if not unicodedata.combining(char)
    )
    brand, sector = plain.split()
    # Three letters and two: long enough not to collide with an ordinary word or a name.
    return f"{brand[:3]}{sector[:2]}".upper()


def greek_company(brand: tuple[str, str], sector: tuple[str, str, str], form: str) -> Company:
    trade_name = f"{brand[0]} {sector[0]}"
    return Company(
        trade_name=trade_name,
        legal_name=f"{trade_name} {form}",
        genitive=f"{brand[0]} {sector[1]}",
        latin=f"{brand[1]} {sector[2]}",
        abbreviation=_initials(trade_name),
        greek=True,
    )


def english_company(brand: str, sector: str, form: str) -> Company:
    trade_name = f"{brand} {sector}"
    return Company(
        trade_name=trade_name,
        legal_name=f"{trade_name} {form}",
        genitive=trade_name,
        latin=trade_name,
        abbreviation=_initials(trade_name),
        greek=False,
    )


def outside_companies(rng: Random) -> list[Company]:
    """Organisations that are not clients, for measuring the precision of `CLIENT`."""
    greek = [
        greek_company(brand, rng.choice(SECTORS_EL), rng.choice(LEGAL_FORMS_EL))
        for brand in OUTSIDE_BRANDS_EL
    ]
    english = [
        english_company(brand, rng.choice(SECTORS_EN), rng.choice(LEGAL_FORMS_EN))
        for brand in OUTSIDE_BRANDS_EN
    ]
    return greek + english
