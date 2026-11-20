import pytest

from gateway.app.core.types import DataType, RowSource, Store
from gateway.app.detect.greek_names import NameKind, name_forms, name_keys
from gateway.app.detect.local import LocalEngine
from gateway.app.detect.patterns import PatternRule
from gateway.app.detect.terms import TermRule
from gateway.app.detect.tokens import name_key
from gateway.tests.detect.conftest import default_patterns, default_terms, found


@pytest.mark.parametrize(
    ("name", "kind", "forms"),
    [
        ("Γιώργος", NameKind.GIVEN_MALE, {"γιωργοσ", "γιωργου", "γιωργο", "γιωργε"}),
        ("Γιάννης", NameKind.GIVEN_MALE, {"γιαννησ", "γιαννη"}),
        ("Κώστας", NameKind.GIVEN_MALE, {"κωστασ", "κωστα"}),
        ("Μαρία", NameKind.GIVEN_FEMALE, {"μαρια", "μαριασ"}),
        ("Ελένη", NameKind.GIVEN_FEMALE, {"ελενη", "ελενησ"}),
        (
            "Παπαδόπουλος",
            NameKind.SURNAME,
            {"παπαδοπουλοσ", "παπαδοπουλου", "παπαδοπουλο", "παπαδοπουλε"},
        ),
        ("Παπαδάκης", NameKind.SURNAME, {"παπαδακησ", "παπαδακη"}),
        ("Γεωργιάδης", NameKind.SURNAME, {"γεωργιαδησ", "γεωργιαδη", "γεωργιαδου"}),
        ("Οικονόμου", NameKind.SURNAME, {"οικονομου"}),
        ("Μιχαήλ", NameKind.GIVEN_MALE, {"μιχαηλ"}),
    ],
)
def test_name_forms_follow_greek_declension(name: str, kind: NameKind, forms: set[str]) -> None:
    assert name_forms(name, kind) == forms


def test_name_keys_agree_across_scripts() -> None:
    keys = name_keys("Παπαδόπουλος", NameKind.SURNAME)
    assert {name_key("Παπαδοπούλου"), name_key("Papadopoulou"), name_key("PAPADOPOULOS")} <= keys


@pytest.mark.parametrize(
    "mention",
    [
        "Helios Shipping S.A.",  # exact
        "Helios Shipping",  # alias
        "HELIOS SHIPPING",  # case
        "Ήλιος Ναυτιλιακή",  # alias in Greek
        "Ήλιου Ναυτιλιακής",  # genitive
        "Ηλιος Ναυτιλιακη",  # no accents
        "Ilios Naftiliaki",  # Greeklish
        "HSA",  # acronym alias
    ],
)
def test_company_term_is_found_in_every_form(rules_only: LocalEngine, mention: str) -> None:
    text = f"στείλε την προσφορά στην {mention} αύριο"
    (finding,) = rules_only.detect(text).findings
    assert (finding.data_type, finding.text) == (DataType.CLIENT, mention)
    assert finding.canonical == "Helios Shipping S.A."
    assert finding.match is not None
    assert (finding.match.store, finding.match.row_id, finding.match.source) == (
        Store.TERMS,
        "client-1",
        RowSource.SYNCED,
    )
    assert finding.match.label == "crm-clients" and finding.tier == "T1"


def test_term_keeps_its_data_type(rules_only: LocalEngine) -> None:
    result = rules_only.detect("status of project kerveros and PRJ-0042?")
    assert found(result) == [("PROJECT", "project kerveros"), ("PROJECT", "PRJ-0042")]
    assert [finding.tier for finding in result.findings] == ["T1", "T0"]


@pytest.mark.parametrize(
    "text", ["the hsa form is ready", "helios is the Greek sun god", "ο ήλιος"]
)
def test_acronyms_and_single_words_need_their_written_form(
    rules_only: LocalEngine, text: str
) -> None:
    assert rules_only.detect(text).findings == ()


@pytest.mark.parametrize(
    "marker",
    ["CONFIDENTIAL", "strictly confidential", "Εμπιστευτικό", "ΑΠΟΡΡΗΤΟ", "internal use only",
     "Attorney-Client Privileged", "empisteftiko"],
)  # fmt: skip
def test_confidentiality_marker_is_flagged_but_not_masked(
    rules_only: LocalEngine, marker: str
) -> None:
    (finding,) = rules_only.detect(f"{marker}: τα στοιχεία του τριμήνου").findings
    assert finding.data_type == DataType.CONFIDENTIAL_MARKER and not finding.maskable
    assert finding.match is not None and finding.match.source is RowSource.DEFAULT
    assert finding.canonical is None


def test_company_row_wins_over_a_default_row(rules_only: LocalEngine) -> None:
    """The contact is in the CRM and both names are in the gazetteer."""
    (finding,) = rules_only.detect("ραντεβού με τη Μαρία Παπαδοπούλου").findings
    assert finding.data_type == DataType.PERSON and finding.recogniser == "term"
    assert finding.match is not None and finding.match.source is RowSource.SYNCED
    assert finding.canonical == "Μαρία Παπαδοπούλου"


def test_company_pattern_wins_over_a_default_pattern() -> None:
    token = "ghp_MadeUpExampleToken0123456789abcdefghij"
    own = PatternRule(
        "own", "our-tokens", r"\bghp_[0-9A-Za-z]{36,}", "SECRET", RowSource.UPLOADED, "custom"
    )
    engine = LocalEngine([*default_patterns(), own], [], None)
    (finding,) = engine.detect(f"token {token}").findings
    assert finding.recogniser == "pattern:our-tokens"


@pytest.mark.parametrize(
    ("text", "people"),
    [
        ("ο Γιώργος Νικολάου υπέγραψε", ["Γιώργος Νικολάου"]),
        ("του Γιώργου Νικολάου", ["Γιώργου Νικολάου"]),
        ("ΝΙΚΟΛΑΟΥ ΓΕΩΡΓΙΟΣ, υπάλληλος", ["ΝΙΚΟΛΑΟΥ ΓΕΩΡΓΙΟΣ"]),
        ("steile to ston Giorgo Nikolaou", ["Giorgo Nikolaou"]),
        ("η Ελένη Παπαδάκη-Γεωργίου", ["Ελένη Παπαδάκη-Γεωργίου"]),
        ("ο κ. Παπαδάκης και η κα Οικονόμου", ["Παπαδάκης", "Οικονόμου"]),
        ("ask Mr Papadakis", ["Papadakis"]),
    ],
)
def test_gazetteer_names_a_person(rules_only: LocalEngine, text: str, people: list[str]) -> None:
    assert found(rules_only.detect(text)) == [(DataType.PERSON, person) for person in people]


@pytest.mark.parametrize(
    "text",
    [
        "Η Νίκη ήρθε μετά τη νίκη",  # a single given name
        "ο Άγγελος και ο Σταύρος",  # two given names, not adjacent
        "στον Παπαδόπουλο",  # a single surname
        "ο γιώργος νικολάου",  # no capitals
    ],
)
def test_a_single_gazetteer_word_is_not_a_finding(rules_only: LocalEngine, text: str) -> None:
    assert rules_only.detect(text).findings == ()


def test_default_gazetteer_size() -> None:
    by_group: dict[str, int] = {}
    for rule in default_terms():
        by_group[rule.group] = by_group.get(rule.group, 0) + 1
    assert by_group["confidentiality-markers"] >= 40
    assert by_group["given-names-male"] + by_group["given-names-female"] >= 300
    assert by_group["surnames"] >= 1000


def test_disabled_term_is_simply_absent() -> None:
    rule = TermRule("r", "Aegean Motors", (), "CLIENT", RowSource.UPLOADED, "client")
    text = "offer for Aegean Motors"
    assert len(LocalEngine([], [rule], None).detect(text).findings) == 1
    assert LocalEngine([], [], None).detect(text).findings == ()


@pytest.mark.parametrize(
    "text",
    [
        '"Confidential Information" means all information disclosed by a party.',
        "information that is identified as confidential or would be regarded as such",
        "anything that qualifies as a trade secret. Either party may end the talks.",
        "the programme offers confidential counselling free of charge",
        "Ζήτησε να μείνει εμπιστευτικό το θέμα της αμοιβής.",
    ],
)
def test_a_marker_word_in_running_prose_is_not_a_marker(rules_only: LocalEngine, text: str) -> None:
    assert rules_only.detect(text).findings == ()


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("Confidential. Tighten the wording of this note.", "Confidential"),
        ("Subject: budget\nInternal use only\nRevenue fell.", "Internal use only"),
        ("[Εμπιστευτικό] Σχέδιο αναδιοργάνωσης", "Εμπιστευτικό"),
        ("this file is marked STRICTLY CONFIDENTIAL by legal", "STRICTLY CONFIDENTIAL"),
        ("Draft attached. Private and confidential. Do not print.", "Private and confidential"),
    ],
)
def test_a_marker_counts_when_it_stands_as_a_label(
    rules_only: LocalEngine, text: str, marker: str
) -> None:
    assert found(rules_only.detect(text)) == [(DataType.CONFIDENTIAL_MARKER, marker)]


@pytest.mark.parametrize(
    ("text", "company"),
    [
        ("χρεώθηκε δύο φορές από την Κοχυλόπετρα Ασφαλιστική χθες", "Κοχυλόπετρα Ασφαλιστική"),
        ("ο λογαριασμός της Κοχυλόπετρας Ασφαλιστικής", "Κοχυλόπετρας Ασφαλιστικής"),
        ("charged twice by Kochylopetra Asfalistiki. Write", "Kochylopetra Asfalistiki"),
        ("meeting me tin Myrtofyllo Viomichaniki avrio", "Myrtofyllo Viomichaniki"),
    ],
)
def test_greek_company_named_by_brand_and_sector(
    rules_only: LocalEngine, text: str, company: str
) -> None:
    (finding,) = rules_only.detect(text).findings
    assert (finding.data_type, finding.text) == (DataType.ORG, company)
    assert finding.recogniser == "org:sector" and finding.match is None


@pytest.mark.parametrize(
    "text",
    [
        "Στην Πληροφορική υπάρχουν πολλές ειδικότητες",
        "η θέση είναι στη Διεύθυνση Πληροφορικής της εταιρείας",
        "το νέο Ασφαλιστικό ψηφίστηκε χθες",
        "σπούδασε Εφαρμοσμένη Πληροφορική στην Αθήνα",
    ],
)
def test_a_sector_word_alone_does_not_make_a_company(rules_only: LocalEngine, text: str) -> None:
    assert rules_only.detect(text).findings == ()
