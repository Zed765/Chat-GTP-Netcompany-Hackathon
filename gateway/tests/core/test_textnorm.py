import pytest

from gateway.app.core.textnorm import entity_key, fold, has_greek, transliterate


def test_fold_ignores_case_accents_and_final_sigma() -> None:
    assert fold("Μαρία") == fold("ΜΑΡΙΑ") == "μαρια"
    assert fold("Νίκος") == "νικοσ"


@pytest.mark.parametrize(
    ("greek", "latin"),
    [
        ("Παπαδόπουλος", "papadopoulos"),
        ("Ευαγγελία", "evangelia"),
        ("Αυτοκίνητο", "aftokinito"),
        ("Θεσσαλονίκη", "thessaloniki"),
    ],
)
def test_transliterate_follows_elot(greek: str, latin: str) -> None:
    assert transliterate(greek) == latin


@pytest.mark.parametrize(
    "mentions",
    [
        ("Μαρία", "Μαρίας", "ΜΑΡΙΑ", "Maria", "maria"),
        ("Παπαδοπούλου", "Παπαδόπουλος", "Papadopoulos", "Papadopoulou", "PAPADOPOULOY"),
        ("Νίκος", "Νίκου", "Nikos", "Nicos"),
        ("Ελένη Παπαδάκη", "Ελένης Παπαδάκη", "Eleni Papadaki"),
        ("Βασίλης", "Vasilis", "Basilis"),
    ],
)
def test_entity_key_links_forms_of_one_name(mentions: tuple[str, ...]) -> None:
    assert len({entity_key(mention) for mention in mentions}) == 1


def test_entity_key_keeps_different_names_apart() -> None:
    assert entity_key("Μαρία") != entity_key("Μάριος Ιωάννου")
    assert entity_key("Helios Shipping") != entity_key("Hellas Shipping")


def test_has_greek() -> None:
    assert has_greek("AFM του πελάτη") and not has_greek("client AFM")
