import asyncio

import pytest
from redis.asyncio import Redis

from gateway.app.core.interfaces import Vault
from gateway.app.core.types import MaskedSpan, PlaceholderInfo, RehydrationReport, Tier
from gateway.app.vault import VaultService
from gateway.tests.vault.helpers import CONVERSATION, finding, found

EMAIL_TEXT = (
    "Dear Maria, please confirm that Maria Papadopoulou (AFM 123456789) is paid at "
    "GR16 0110 1250 0000 0001 2300 695. Confidential."
)
EMAIL_ENTITIES = {
    "Maria Papadopoulou": "PERSON",
    "Maria": "PERSON",
    "123456789": "AFM",
    "GR16 0110 1250 0000 0001 2300 695": "IBAN",
}


async def test_findings_become_placeholders_with_spans_in_original_coordinates(
    vault: VaultService,
) -> None:
    checked: Vault = vault
    marker = finding("CONFIDENTIAL_MARKER", EMAIL_TEXT.index("Confidential"), "Confidential")
    findings = [*found(EMAIL_TEXT, EMAIL_ENTITIES), marker.model_copy(update={"maskable": False})]

    result = await checked.mask(CONVERSATION, EMAIL_TEXT, findings)

    assert result.text == (
        "Dear <PERSON_1>, please confirm that <PERSON_1> (AFM <AFM_1>) is paid at <IBAN_1>. "
        "Confidential."
    )
    assert [(span.placeholder, EMAIL_TEXT[span.start : span.end]) for span in result.spans] == [
        ("<PERSON_1>", "Maria"),
        ("<PERSON_1>", "Maria Papadopoulou"),
        ("<AFM_1>", "123456789"),
        ("<IBAN_1>", "GR16 0110 1250 0000 0001 2300 695"),
    ]
    assert result.unmasked == (findings[-1],)


async def test_a_span_carries_what_the_finding_knew(vault: VaultService) -> None:
    detected = finding("AFM", 4, "123456789", tier=Tier.T0, recogniser="afm")
    result = await vault.mask(CONVERSATION, "AFM 123456789", [detected])
    assert result.spans == (
        MaskedSpan(
            start=4,
            end=13,
            placeholder="<AFM_1>",
            data_type="AFM",
            tier=Tier.T0,
            recogniser="afm",
        ),
    )


async def test_one_entity_in_three_forms_across_three_turns_has_one_placeholder(
    vault: VaultService,
) -> None:
    turns = [
        ("Maria Papadopoulou asked for an invoice.", "Maria Papadopoulou"),
        ("Did Ms Papadopoulou reply? Tell Maria we called.", "Ms Papadopoulou"),
        ("Στείλε το τιμολόγιο της Μαρίας σήμερα.", "Μαρίας"),
    ]
    used: set[str] = set()
    for text, form in turns:
        result = await vault.mask(
            CONVERSATION, text, found(text, {form: "PERSON", "Maria": "PERSON"})
        )
        assert form not in result.text
        used.update(span.placeholder for span in result.spans)

    assert used == {"<PERSON_1>"}
    assert await vault.describe(CONVERSATION) == [
        PlaceholderInfo(placeholder="<PERSON_1>", data_type="PERSON")
    ]


async def test_a_placeholder_restores_to_the_first_form_seen(vault: VaultService) -> None:
    for text in ("Η Μαρία Παπαδοπούλου", "της Μαρίας Παπαδοπούλου", "Maria"):
        await vault.mask(CONVERSATION, text, found(text, {text.split(" ", 1)[-1]: "PERSON"}))
    await vault.mask(CONVERSATION, "Maria", found("Maria", {"Maria": "PERSON"}))

    restored, _ = await vault.resolve(CONVERSATION, "Dear <PERSON_1>")

    assert restored == "Dear Μαρία Παπαδοπούλου"


async def test_two_people_with_one_first_name_are_never_merged(vault: VaultService) -> None:
    text = "Maria Papadopoulou and Maria Georgiou met. Maria left early."
    entities = {"Maria Papadopoulou": "PERSON", "Maria Georgiou": "PERSON", "Maria": "PERSON"}

    result = await vault.mask(CONVERSATION, text, found(text, entities))

    assert result.text == "<PERSON_1> and <PERSON_2> met. <PERSON_3> left early."
    restored, _ = await vault.resolve(CONVERSATION, result.text)
    assert restored == text


async def test_a_client_found_by_term_and_by_name_recogniser_is_one_entity(
    vault: VaultService,
) -> None:
    first = "Offer for Helios Shipping SA."
    known = finding("CLIENT", 10, "Helios Shipping SA", canonical="Helios Shipping SA")
    assert (await vault.mask(CONVERSATION, first, [known])).text == "Offer for <CLIENT_1>."

    second = "Helios called; HSC wants a discount."
    findings = [
        finding("ORG", 0, "Helios"),
        finding("CLIENT", 15, "HSC", canonical="Helios Shipping SA"),
    ]
    result = await vault.mask(CONVERSATION, second, findings)

    assert result.text == "<CLIENT_1> called; <CLIENT_1> wants a discount."
    assert [span.data_type for span in result.spans] == ["ORG", "CLIENT"]


async def test_custom_types_get_their_own_placeholders(vault: VaultService) -> None:
    text = "Project Aeolus (PRJ-2024-0042) replaces PRJ-2024-0077."
    entities = {
        "Aeolus": "PROJECT",
        "PRJ-2024-0042": "project code",
        "PRJ-2024-0077": "project code",
    }

    result = await vault.mask(CONVERSATION, text, found(text, entities))

    assert result.text == "Project <PROJECT_1> (<PROJECT_CODE_1>) replaces <PROJECT_CODE_2>."
    assert (await vault.resolve(CONVERSATION, result.text))[0] == text


async def test_a_secret_is_redacted_one_way(vault: VaultService, redis: Redis) -> None:
    text = "Use sk-test-abcd1234 for Maria Papadopoulou."
    entities = {"sk-test-abcd1234": "SECRET", "Maria Papadopoulou": "PERSON"}

    result = await vault.mask(CONVERSATION, text, found(text, entities))

    assert result.text == "Use <SECRET_REDACTED> for <PERSON_1>."
    assert [span.placeholder for span in result.spans] == ["<SECRET_REDACTED>", "<PERSON_1>"]
    restored, report = await vault.resolve(CONVERSATION, result.text)
    assert restored == "Use <SECRET_REDACTED> for Maria Papadopoulou."
    assert report == RehydrationReport(sent=0, returned=1)
    assert [info.placeholder for info in await vault.describe(CONVERSATION)] == ["<PERSON_1>"]


async def test_a_text_with_only_secrets_never_reaches_redis(
    vault: VaultService, redis: Redis
) -> None:
    text = "token sk-test-abcd1234"
    await vault.mask(CONVERSATION, text, found(text, {"sk-test-abcd1234": "SECRET"}))
    await vault.mask(CONVERSATION, "nothing to see", [])
    assert await redis.keys("*") == []


async def test_a_value_in_an_encoded_run_restores_to_the_run(vault: VaultService) -> None:
    run = "MTIzNDU2Nzg5"
    text = f"AFM 123456789, encoded {run}, again {run}."
    findings = [
        finding("AFM", 4, "123456789"),
        *found(text, {run: "AFM"}, encoded=True, canonical="123456789"),
    ]

    result = await vault.mask(CONVERSATION, text, findings)

    assert result.text == "AFM <AFM_1>, encoded <AFM_2>, again <AFM_2>."
    assert [span.encoded for span in result.spans] == [False, True, True]
    assert (await vault.resolve(CONVERSATION, result.text))[0] == text


async def test_text_that_is_already_masked_passes_through_untouched(vault: VaultService) -> None:
    first = "Client Maria Papadopoulou, AFM 123456789."
    masked = await vault.mask(CONVERSATION, first, found(first, EMAIL_ENTITIES))
    tool_result = f"CRM record: {masked.text} Owner: <SECRET_REDACTED>."

    again = await vault.mask(
        CONVERSATION,
        tool_result,
        [
            finding("ORG", tool_result.index("PERSON_1"), "PERSON_1"),
            finding("AFM", tool_result.index("<AFM_1>"), "<AFM_1>"),
            finding("SECRET", tool_result.index("SECRET_REDACTED"), "SECRET_REDACTED"),
        ],
    )

    assert again.text == tool_result
    assert again.spans == ()
    assert len(await vault.describe(CONVERSATION)) == 2


async def test_new_entities_in_already_masked_text_continue_the_numbering(
    vault: VaultService,
) -> None:
    await vault.mask(
        CONVERSATION, "Maria Papadopoulou", [finding("PERSON", 0, "Maria Papadopoulou")]
    )
    text = "<PERSON_1> works with Nikos Georgiou."

    result = await vault.mask(CONVERSATION, text, found(text, {"Nikos Georgiou": "PERSON"}))

    assert result.text == "<PERSON_1> works with <PERSON_2>."
    restored, _ = await vault.resolve(CONVERSATION, result.text)
    assert restored == "Maria Papadopoulou works with Nikos Georgiou."


@pytest.mark.parametrize(
    "spans",
    [
        [(6, "Papadopoulou"), (0, "Maria")],
        [(0, "Maria Papadopoulou"), (6, "Papadopoulou")],
        [(6, "Papadopoulou and more")],
    ],
)
async def test_findings_that_break_the_contract_are_refused(
    vault: VaultService, spans: list[tuple[int, str]]
) -> None:
    findings = [finding("PERSON", start, surface) for start, surface in spans]
    with pytest.raises(ValueError, match="sorted"):
        await vault.mask(CONVERSATION, "Maria Papadopoulou", findings)


async def test_conversations_do_not_share_placeholders_or_values(vault: VaultService) -> None:
    other = "fedcba9876543210:another"
    await vault.mask(
        CONVERSATION, "Maria Papadopoulou", [finding("PERSON", 0, "Maria Papadopoulou")]
    )
    result = await vault.mask(other, "Nikos Georgiou", [finding("PERSON", 0, "Nikos Georgiou")])

    assert result.text == "<PERSON_1>"
    assert (await vault.resolve(other, "<PERSON_1>"))[0] == "Nikos Georgiou"
    assert (await vault.resolve(CONVERSATION, "<PERSON_1>"))[0] == "Maria Papadopoulou"
    assert await vault.resolve("0123456789abcdef:never used", "<PERSON_1>") == (
        "<PERSON_1>",
        RehydrationReport(sent=0, returned=0, unresolved=("<PERSON_1>",)),
    )


async def test_texts_of_one_conversation_masked_at_once_never_share_a_number(
    vault: VaultService,
) -> None:
    names = [f"Client {number} Ltd" for number in range(16)]

    results = await asyncio.gather(
        *(vault.mask(CONVERSATION, name, [finding("PERSON", 0, name)]) for name in names)
    )

    placeholders = [result.text for result in results]
    assert sorted(placeholders) == sorted(f"<PERSON_{n}>" for n in range(1, len(names) + 1))
    for name, placeholder in zip(names, placeholders, strict=True):
        assert (await vault.resolve(CONVERSATION, placeholder))[0] == name


async def test_describe_lists_placeholders_and_types_without_values(vault: VaultService) -> None:
    await vault.mask(CONVERSATION, EMAIL_TEXT, found(EMAIL_TEXT, EMAIL_ENTITIES))
    text = " ".join(f"Client{n} Name{n}" for n in range(11))
    await vault.mask(
        CONVERSATION, text, found(text, {f"Client{n} Name{n}": "CLIENT" for n in range(11)})
    )

    described = await vault.describe(CONVERSATION)

    assert [info.placeholder for info in described] == [
        "<AFM_1>",
        *(f"<CLIENT_{n}>" for n in range(1, 12)),
        "<IBAN_1>",
        "<PERSON_1>",
    ]
    assert {info.data_type for info in described} == {"AFM", "CLIENT", "IBAN", "PERSON"}


async def test_a_restored_text_reads_again_as_the_model_saw_it(vault: VaultService) -> None:
    await vault.mask(CONVERSATION, EMAIL_TEXT, found(EMAIL_TEXT, EMAIL_ENTITIES))
    written = "Reply sent to <PERSON_1>, AFM <AFM_1>, in 2025."
    restored, _ = await vault.resolve(CONVERSATION, written)
    unrelated = "A name the vault does not hold: Nikos Georgiou."

    assert restored != written
    assert await vault.as_sent(CONVERSATION, [restored, unrelated]) == [written, unrelated]
    assert await vault.as_sent("another-conversation", [restored]) == [restored]
