"""The model path, proved with a fake model. It has never run against the real one."""

from collections.abc import Callable

from seeder.compose.rewrite import entities_survive, rewrite_filled, rewrite_text
from seeder.compose.slots import fill, value

ENTITIES = ("Μαρία Παπαδοπούλου", "094014201", "GR1601101250000000012300695")
TEXT = (
    "Η Μαρία Παπαδοπούλου, με ΑΦΜ 094014201, ζήτησε επιστροφή "
    "στον λογαριασμό GR1601101250000000012300695."
)


class FakeModel:
    """Applies a function to what it is sent, and remembers what that was."""

    def __init__(self, answer: Callable[[str], str]) -> None:
        self._answer = answer
        self.received: list[str] = []

    def rewrite(self, instructions: str, text: str) -> str:
        self.received.append(text)
        return self._answer(text)


def test_a_rewrite_keeps_every_entity_and_never_shows_one_to_the_model() -> None:
    model = FakeModel(lambda text: text.replace("ζήτησε επιστροφή", "θέλει τα χρήματα πίσω"))
    rewritten = rewrite_text(model, TEXT, ENTITIES, "el")
    assert "θέλει τα χρήματα πίσω" in rewritten
    assert entities_survive(rewritten, ENTITIES)
    assert not any(entity in model.received[0] for entity in ENTITIES)


def test_a_rewrite_that_loses_an_entity_is_thrown_away() -> None:
    assert (
        rewrite_text(FakeModel(lambda text: text.replace("⟦1⟧", "")), TEXT, ENTITIES, "el") == TEXT
    )
    assert rewrite_text(FakeModel(lambda text: f"{text} ⟦9⟧"), TEXT, ENTITIES, "el") == TEXT


def test_labels_move_with_their_entities_when_a_prompt_is_rewritten() -> None:
    slots = {"name": value("Maria Papadopoulou", "PERSON"), "afm": value("094014201", "AFM")}
    filled = fill("Write to {name} about tax number {afm}.", slots)
    model = FakeModel(lambda text: "Regarding tax number ⟦1⟧: please write a note to ⟦0⟧ today.")
    rewritten = rewrite_filled(model, filled, "en")
    assert rewritten.text == (
        "Regarding tax number 094014201: please write a note to Maria Papadopoulou today."
    )
    assert [(label.type, label.text) for label in rewritten.labels] == [
        ("AFM", "094014201"),
        ("PERSON", "Maria Papadopoulou"),
    ]
    for label in rewritten.labels:
        assert rewritten.text[label.start : label.end] == label.text


def test_a_prompt_rewrite_that_repeats_or_drops_a_label_is_thrown_away() -> None:
    slots = {"name": value("Maria Papadopoulou", "PERSON")}
    filled = fill("Call {name}.", slots)
    assert rewrite_filled(FakeModel(lambda text: "Call ⟦0⟧ and ⟦0⟧."), filled, "en") == filled
    assert rewrite_filled(FakeModel(lambda text: "Call her."), filled, "en") == filled
