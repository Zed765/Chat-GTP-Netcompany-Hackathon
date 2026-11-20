import pytest

from gateway.app.vault.linking import Linker, Mention, link_all, mention_of
from gateway.tests.vault.helpers import finding


def mention(surface: str, data_type: str = "PERSON", **fields: object) -> Mention:
    return mention_of(finding(data_type, 0, surface, **fields), surface)


def link(*mentions: Mention) -> list[str]:
    return link_all(Linker({}), mentions)


@pytest.mark.parametrize(
    "forms",
    [
        ("Maria Papadopoulou", "Μαρία Παπαδοπούλου", "ΜΑΡΙΑΣ ΠΑΠΑΔΟΠΟΥΛΟΥ", "maria papadopoulou"),
        ("Maria Papadopoulou", "Papadopoulou Maria", "Ms Maria Papadopoulou"),
        ("Μαρία Παπαδοπούλου", "κα Μαρία Παπαδοπούλου", "κυρίας Μαρίας Παπαδοπούλου"),
        ("Νίκος", "Νίκου", "Νίκο", "Nikos", "NIKOS"),
        ("Ελένη Παπαδάκη", "Ελένης Παπαδάκη", "Eleni Papadaki"),
        ("Helios Shipping SA", "HELIOS SHIPPING SA", "helios  shipping s.a."),
    ],
)
def test_forms_of_one_name_share_a_key(forms: tuple[str, ...]) -> None:
    assert len({mention(form).keys for form in forms}) == 1


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("Μαρία", "Μάριος"),
        ("Νίκος", "Νίκη"),
        ("Δημήτρης", "Δήμητρα"),
        ("Κωνσταντίνος", "Κωνσταντίνα"),
        ("Γεωργία", "Γεωργίου"),
        ("Maria Papadopoulou", "Marios Papadopoulos"),
        ("Helios 2", "Helios 3"),
        ("PRJ-2024-0042", "PRJ-2024-0077"),
    ],
)
def test_different_names_with_one_stem_stay_apart(one: str, other: str) -> None:
    first, second = link(mention(one), mention(other))
    assert first != second


@pytest.mark.parametrize(
    ("data_type", "one", "other", "same"),
    [
        ("IBAN", "GR16 0110 1250 0000 0001 2300 695", "gr1601101250000000012300695", True),
        ("PHONE", "210-1234567", "210 123 4567", True),
        ("AFM", "123456789", "123456780", False),
        ("EMAIL", "Maria@Helios.Example", "maria@helios.example", True),
        ("EMAIL", "m.aria@helios.example", "maria@helios.example", False),
    ],
)
def test_identifiers_link_by_normalised_value(
    data_type: str, one: str, other: str, same: bool
) -> None:
    first, second = link(mention(one, data_type), mention(other, data_type))
    assert (first == second) is same


def test_the_same_digits_under_two_types_are_two_entities() -> None:
    assert link(mention("123456789", "AFM"), mention("123456789", "PHONE")) == [
        "<AFM_1>",
        "<PHONE_1>",
    ]


def test_a_shorter_mention_joins_the_one_entity_that_contains_it() -> None:
    assert link(
        mention("Maria Papadopoulou"),
        mention("Nikos Georgiou"),
        mention("Maria"),
        mention("Ms Papadopoulou"),
        mention("κ. Γεωργίου"),
    ) == ["<PERSON_1>", "<PERSON_2>", "<PERSON_1>", "<PERSON_1>", "<PERSON_2>"]


def test_a_first_name_shared_by_two_people_gets_a_placeholder_of_its_own() -> None:
    assert link(
        mention("Maria Papadopoulou"),
        mention("Maria Georgiou"),
        mention("Maria"),
        mention("Papadopoulou"),
        mention("Μαρίας"),
    ) == ["<PERSON_1>", "<PERSON_2>", "<PERSON_3>", "<PERSON_1>", "<PERSON_3>"]


def test_a_mention_keeps_the_placeholder_it_was_given_when_it_later_turns_ambiguous() -> None:
    linker = Linker({})
    assert link_all(linker, [mention("Maria Papadopoulou"), mention("Maria")]) == [
        "<PERSON_1>",
        "<PERSON_1>",
    ]
    assert link_all(linker, [mention("Maria Georgiou"), mention("Maria")]) == [
        "<PERSON_2>",
        "<PERSON_1>",
    ]


def test_the_order_of_mentions_within_one_text_does_not_matter() -> None:
    assert link(mention("Maria"), mention("Nikos"), mention("Maria Papadopoulou")) == [
        "<PERSON_1>",
        "<PERSON_2>",
        "<PERSON_1>",
    ]


def test_a_longer_name_does_not_join_a_shorter_one_from_an_earlier_text() -> None:
    linker = Linker({})
    assert link_all(linker, [mention("Maria")]) == ["<PERSON_1>"]
    assert link_all(linker, [mention("Maria Papadopoulou"), mention("Maria")]) == [
        "<PERSON_2>",
        "<PERSON_1>",
    ]


def test_people_organisations_and_clients_share_one_namespace() -> None:
    assert link(
        mention("Helios Shipping SA", "CLIENT"),
        mention("Helios Shipping", "ORG"),
        mention("Maria Papadopoulou", "CLIENT"),
        mention("Maria", "PERSON"),
    ) == ["<CLIENT_1>", "<CLIENT_1>", "<CLIENT_2>", "<CLIENT_2>"]


def test_other_types_link_only_within_their_own_type() -> None:
    assert link(
        mention("Athens Trading", "ORG"),
        mention("Athens", "LOCATION"),
        mention("Helios", "PROJECT"),
    ) == ["<ORG_1>", "<LOCATION_1>", "<PROJECT_1>"]


def test_the_canonical_name_links_an_alias_to_its_entity() -> None:
    assert (
        link(
            mention("HSC", "CLIENT", canonical="Helios Shipping Company"),
            mention("Helios Shipping", "ORG"),
            mention("Ήλιος Ναυτιλιακή", "CLIENT", canonical="Helios Shipping Company"),
            mention("HSC", "ORG"),
        )
        == ["<CLIENT_1>"] * 4
    )


def test_an_encoded_run_never_shares_a_placeholder_with_the_plain_value() -> None:
    run = "MTIzNDU2Nzg5"
    assert link(
        mention("123456789", "AFM"),
        mention(run, "AFM", encoded=True, canonical="123456789"),
        mention(run, "AFM", encoded=True, canonical="123456789"),
    ) == ["<AFM_1>", "<AFM_2>", "<AFM_2>"]


def test_the_linker_reports_what_to_store() -> None:
    linker = Linker({})
    link_all(linker, [mention("Maria Papadopoulou"), mention("Maria"), mention("123456789", "AFM")])
    assert linker.created == {"<PERSON_1>": "Maria Papadopoulou", "<AFM_1>": "123456789"}

    again = Linker(linker.changed)
    assert link_all(again, [mention("ΜΑΡΙΑ ΠΑΠΑΔΟΠΟΥΛΟΥ"), mention("Papadopoulou")]) == [
        "<PERSON_1>",
        "<PERSON_1>",
    ]
    assert again.created == {}
