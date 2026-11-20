"""The protected-data API against a real database: imports, switches, reload."""

import asyncio
import logging
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select, text

from gateway.app.core.types import DataType, RowSource
from gateway.app.main import create_app
from gateway.app.protected.models import ProtectedTerm
from gateway.tests.conftest import Api
from gateway.tests.protected.conftest import EMPLOYEE
from gateway.tests.protected.helpers import (
    CONTRACT,
    DISTINCTIVE_PHRASES,
    RECIPE,
    docx_bomb,
    docx_bytes,
    excerpt,
    pdf_bytes,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_stores")]

CLIENTS = [
    {
        "id": "c-1",
        "kind": "company",
        "legal_name": "Zephyros Maritime Ltd",
        "trade_name": "Zephyros Maritime",
        "aliases": ["ZML", "Ζέφυρος Ναυτιλιακή"],
        "contacts": [{"name": "Δανάη Ραφαηλίδου", "role": "CFO"}],
    },
    {"id": "c-2", "kind": "individual", "legal_name": "Orestis Vamvakas", "aliases": []},
]


async def _test(api: Api, headers: dict[str, str], prompt: str) -> dict[str, Any]:
    response = await api.client.post("/api/protected/test", json={"text": prompt}, headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _types(result: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(finding["data_type"], finding["source"]) for finding in result["findings"]]


async def test_default_pack_loads_once_and_serves_a_clean_install(
    api: Api, analyst: dict[str, str]
) -> None:
    summary = (await api.client.get("/api/protected/summary", headers=analyst)).json()
    assert summary["pack_version"] == "2026.11.5"
    layers = {
        store["store"]: {layer["source"]: layer["rows"] for layer in store["layers"]}
        for store in summary["stores"]
    }
    assert layers["terms"]["default"] > 2000 and layers["patterns"]["default"] >= 50
    assert layers["terms"]["uploaded"] == layers["terms"]["synced"] == 0
    assert set(DataType.BUILT_IN) <= set(summary["data_types"])
    groups = {group["group"] for store in summary["stores"] for group in store["groups"]}
    assert {"confidentiality-markers", "surnames", "code-hosting"} <= groups

    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    again = (await api.client.get("/api/protected/summary", headers=analyst)).json()
    assert again["stores"] == summary["stores"]

    prompt = (
        "Ο Γιώργος Νικολάου, ΑΦΜ 094014201, IBAN GR1601101250000000012300695, "
        "κλειδί sk_live_MadeUpExampleKey0123456789"
    )
    result = await _test(api, analyst, prompt)
    assert [finding["data_type"] for finding in result["findings"]] == [
        "PERSON", "AFM", "IBAN", "SECRET"
    ]  # fmt: skip
    assert result["masked_text"] == (
        "Ο <PERSON_1>, ΑΦΜ <AFM_1>, IBAN <IBAN_1>, κλειδί <SECRET_REDACTED>"
    )


async def test_only_an_analyst_may_use_the_stores(api: Api) -> None:
    for method, path in (
        ("GET", "/summary"),
        ("POST", "/terms/sync"),
        ("POST", "/demo-data/remove"),
    ):
        anonymous = await api.client.request(method, f"/api/protected{path}")
        employee = await api.client.request(
            method, f"/api/protected{path}", headers=api.as_(EMPLOYEE)
        )
        assert (anonymous.status_code, employee.status_code) == (401, 403)


async def test_term_import_reports_bad_rows_and_applies_to_the_next_request(
    api: Api, analyst: dict[str, str]
) -> None:
    prompt = "Ετοίμασε προσφορά για τη Ζέφυρος Ναυτιλιακή και το project Meltemi"
    assert _types(await _test(api, analyst, prompt)) == [("ORG", None)]
    rows = [
        {"term": "Zephyros Maritime Ltd", "aliases": ["Ζέφυρος Ναυτιλιακή", "ZML"]},
        {"term": "Meltemi", "data_type": "project"},
        {"term": "X"},
        {"aliases": ["no term"]},
        {"term": "Aegean Motors", "data_type": "CONTRACT"},
        {"term": "zephyros maritime ltd"},
    ]
    response = await api.client.post("/api/protected/terms", json=rows, headers=analyst)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["imported"], result["duplicates"]) == (2, 1)
    assert [error["row"] for error in result["errors"]] == [3, 4, 5]
    assert "document category" in result["errors"][2]["message"]

    found = await _test(api, analyst, prompt)
    assert _types(found) == [("CLIENT", "uploaded"), ("PROJECT", "uploaded")]
    assert (
        found["findings"][0]["match_label"] == "client" and found["findings"][0]["store"] == "terms"
    )
    assert "PROJECT" in api.services.protected.data_types()
    default_only = api.services.detector.scoped([RowSource.DEFAULT])
    generic = (await default_only.detect_local(prompt)).findings
    assert [(finding.data_type, finding.match) for finding in generic] == [("ORG", None)]

    page = (
        await api.client.get("/api/protected/terms?source=uploaded&q=ζέφ", headers=analyst)
    ).json()
    assert page["total"] == 1 and page["items"][0]["term"] == "Zephyros Maritime Ltd"
    assert page["items"][0]["aliases"] == ["Ζέφυρος Ναυτιλιακή", "ZML"]


async def test_terms_are_encrypted_at_rest(api: Api, analyst: dict[str, str]) -> None:
    rows = [{"term": "Zephyros Maritime Ltd", "aliases": ["Notos Lines"]}]
    await api.client.post("/api/protected/terms", json=rows, headers=analyst)
    async with api.services.db.session() as session:
        dump = (
            await session.execute(
                text("SELECT string_agg(row_to_json(t)::text, ' ') FROM protected_terms t")
            )
        ).scalar_one()
        stored = (
            await session.execute(
                select(ProtectedTerm).where(ProtectedTerm.source == RowSource.UPLOADED.value)
            )
        ).scalar_one()
    for secret in ("Zephyros", "Notos", "Παπαδόπουλος", "Confidential"):
        assert secret not in dump
    assert b"Zephyros" not in stored.term and stored.aliases is not None
    assert b"Notos" not in stored.aliases


async def test_term_file_upload_accepts_csv_and_json(api: Api, analyst: dict[str, str]) -> None:
    csv_file = (
        "term,aliases,data_type\nBoreas Energy,Boreas|Βορέας Ενεργειακή,\nMeltemi,,PROJECT\n,,\n"
    )
    response = await api.client.post(
        "/api/protected/terms/upload",
        files={"file": ("terms.csv", csv_file.encode("utf-8-sig"), "text/csv")},
        headers=analyst,
    )
    assert response.json() == {
        "imported": 2,
        "duplicates": 0,
        "errors": [{"row": 3, "message": "term must be 2 to 200 characters long"}],
    }
    json_file = '["Notos Lines", {"term": "Boreas Energy"}]'
    response = await api.client.post(
        "/api/protected/terms/upload",
        files={"file": ("terms.json", json_file.encode(), "application/json")},
        headers=analyst,
    )
    assert (response.json()["imported"], response.json()["duplicates"]) == (1, 1)
    assert _types(await _test(api, analyst, "meeting with Βορέα Ενεργειακής")) == [
        ("CLIENT", "uploaded")
    ]
    bad = await api.client.post(
        "/api/protected/terms/upload",
        files={"file": ("terms.csv", b"name\nBoreas\n", "text/csv")},
        headers=analyst,
    )
    assert bad.status_code == 422 and "term" in bad.json()["detail"]


@respx.mock
async def test_crm_sync_brings_clients_and_contacts(api: Api, analyst: dict[str, str]) -> None:
    export = respx.get("http://mcp-crm:9001/export/clients")
    export.mock(return_value=httpx.Response(200, json=CLIENTS))
    response = await api.client.post("/api/protected/terms/sync", headers=analyst)
    assert response.json() == {"imported": 3, "duplicates": 0, "errors": []}

    found = await _test(api, analyst, "Η κα Δανάη Ραφαηλίδου της ZML ζήτησε νέα τιμή")
    assert _types(found) == [("CLIENT", "synced"), ("CLIENT", "synced")]
    assert [finding["match_label"] for finding in found["findings"]] == [
        "crm-contacts", "crm-clients"
    ]  # fmt: skip
    assert found["masked_text"] == "Η κα <CLIENT_1> της <CLIENT_2> ζήτησε νέα τιμή"

    export.mock(return_value=httpx.Response(200, json=CLIENTS[:1]))
    again = await api.client.post("/api/protected/terms/sync", headers=analyst)
    assert again.json()["imported"] == 2
    page = (await api.client.get("/api/protected/terms?source=synced", headers=analyst)).json()
    assert page["total"] == 2

    export.mock(return_value=httpx.Response(503))
    down = await api.client.post("/api/protected/terms/sync", headers=analyst)
    assert down.status_code == 502 and "CRM" in down.json()["detail"]
    assert (await api.client.get("/api/protected/terms?source=synced", headers=analyst)).json()[
        "total"
    ] == 2


async def test_switching_a_default_row_off_survives_a_pack_upgrade(
    api: Api, analyst: dict[str, str]
) -> None:
    prompt = "CONFIDENTIAL: σχέδιο προϋπολογισμού"
    assert _types(await _test(api, analyst, prompt)) == [("CONFIDENTIAL_MARKER", "default")]
    page = (
        await api.client.get(
            "/api/protected/terms?group=confidentiality-markers&q=confidential", headers=analyst
        )
    ).json()
    marker = next(item for item in page["items"] if item["term"] == "Confidential")

    switched = await api.client.patch(
        f"/api/protected/terms/{marker['id']}", json={"enabled": False}, headers=analyst
    )
    assert switched.json()["enabled"] is False
    assert _types(await _test(api, analyst, prompt)) == []

    refused = await api.client.delete(f"/api/protected/terms/{marker['id']}", headers=analyst)
    assert refused.status_code == 409 and "switched off" in refused.json()["detail"]

    async with api.services.db.session() as session:
        await session.execute(
            text("UPDATE protected_terms SET pack_version = 'older' WHERE source = 'default'")
        )
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    assert _types(await _test(api, analyst, prompt)) == []
    page = (
        await api.client.get(
            "/api/protected/terms?group=confidentiality-markers&q=confidential", headers=analyst
        )
    ).json()
    upgraded = next(item for item in page["items"] if item["term"] == "Confidential")
    assert upgraded["enabled"] is False and upgraded["id"] != marker["id"]


async def test_switching_a_default_group(api: Api, analyst: dict[str, str]) -> None:
    prompt = "Internal use only. Top secret."
    assert len((await _test(api, analyst, prompt))["findings"]) == 2
    page = (await api.client.get("/api/protected/terms?q=top secret", headers=analyst)).json()
    await api.client.patch(
        f"/api/protected/terms/{page['items'][0]['id']}", json={"enabled": False}, headers=analyst
    )
    off = await api.client.patch(
        "/api/protected/groups/terms/confidentiality-markers",
        json={"enabled": False},
        headers=analyst,
    )
    assert off.status_code == 200
    assert (await _test(api, analyst, prompt))["findings"] == []
    summary = (await api.client.get("/api/protected/summary", headers=analyst)).json()
    markers = next(
        group
        for group in summary["stores"][0]["groups"]
        if group["group"] == "confidentiality-markers"
    )
    assert markers["enabled"] is False and markers["data_type"] == "CONFIDENTIAL_MARKER"

    await api.client.patch(
        "/api/protected/groups/terms/confidentiality-markers",
        json={"enabled": True},
        headers=analyst,
    )
    found = await _test(api, analyst, prompt)
    assert [prompt[f["start"] : f["end"]] for f in found["findings"]] == ["Internal use only"]
    missing = await api.client.patch(
        "/api/protected/groups/terms/no-such-group", json={"enabled": False}, headers=analyst
    )
    assert missing.status_code == 404


async def test_custom_pattern_is_validated_by_re2_and_joins_t0(
    api: Api, analyst: dict[str, str]
) -> None:
    bad = await api.client.post(
        "/api/protected/patterns",
        json={"name": "look-behind", "regex": r"(?<=id:)\d+", "data_type": "BADGE"},
        headers=analyst,
    )
    assert bad.status_code == 422 and "RE2" in bad.json()["detail"]

    body = {"name": "project code", "regex": r"\bPRJ-[0-9]{4}\b", "data_type": "project_code"}
    added = await api.client.post(
        "/api/protected/patterns?source=seeded", json=body, headers=analyst
    )
    assert added.status_code == 200, added.text
    pattern = added.json()
    assert (pattern["source"], pattern["data_type"], pattern["enabled"]) == (
        "seeded", "PROJECT_CODE", True
    )  # fmt: skip
    twice = await api.client.post(
        "/api/protected/patterns?source=seeded", json=body, headers=analyst
    )
    assert twice.status_code == 409

    found = await _test(api, analyst, "status of PRJ-0042?")
    assert _types(found) == [("PROJECT_CODE", "seeded")]
    assert found["findings"][0]["recogniser"] == "pattern:project code"
    assert found["masked_text"] == "status of <PROJECT_CODE_1>?"

    await api.client.patch(
        f"/api/protected/patterns/{pattern['id']}", json={"enabled": False}, headers=analyst
    )
    assert _types(await _test(api, analyst, "status of PRJ-0042?")) == []
    deleted = await api.client.delete(f"/api/protected/patterns/{pattern['id']}", headers=analyst)
    assert deleted.status_code == 204
    listed = (await api.client.get("/api/protected/patterns?source=seeded", headers=analyst)).json()
    assert listed == []


async def test_uploaded_document_is_detected_and_its_text_is_kept_nowhere(
    api: Api, analyst: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    paste = f"Please summarise the following for me: {excerpt(CONTRACT, 60, 110)}"
    assert (await _test(api, analyst, paste))["categories"] == []

    with caplog.at_level(logging.DEBUG):
        upload = await api.client.post(
            "/api/protected/documents",
            files={"file": ("msa.txt", CONTRACT.encode(), "text/plain")},
            data={"label": "MSA Zephyros", "category": "contract"},
            headers=analyst,
        )
    assert upload.status_code == 200, upload.text
    document = upload.json()["document"]
    assert upload.json()["duplicate"] is False
    assert (document["category"], document["source"], document["language"]) == (
        "CONTRACT", "uploaded", "en"
    )  # fmt: skip
    assert document["chunks"] >= 1
    assert document["embedder_id"] == "openai:text-embedding-3-large"

    result = await _test(api, analyst, paste)
    (category,) = result["categories"]
    assert (category["category"], category["tier"], category["conclusive"]) == (
        "CONTRACT",
        "T2",
        True,
    )
    assert category["evidence"] == 'matches "MSA Zephyros"'
    assert (category["store"], category["source"]) == ("fingerprints", "uploaded")
    assert "T2" in result["tiers_run"]
    assert (await _test(api, analyst, f"Διόρθωσε το κείμενο: {RECIPE}"))["categories"] == []

    async with api.services.db.session() as session:
        tables = (
            await session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ).scalars()
        for table in list(tables):
            dump = (
                await session.execute(
                    text(f"SELECT string_agg(row_to_json(t)::text, ' ') FROM {table} t")  # noqa: S608
                )
            ).scalar_one()
            for phrase in DISTINCTIVE_PHRASES:
                assert phrase not in (dump or ""), f"document text found in {table}"
    assert not any(phrase in caplog.text for phrase in DISTINCTIVE_PHRASES)

    again = await api.client.post(
        "/api/protected/documents",
        files={"file": ("copy.txt", CONTRACT.encode(), "text/plain")},
        data={"label": "A copy", "category": "CONTRACT"},
        headers=analyst,
    )
    assert again.json()["duplicate"] is True and again.json()["document"]["id"] == document["id"]

    await api.client.delete(f"/api/protected/documents/{document['id']}", headers=analyst)
    assert (await _test(api, analyst, paste))["categories"] == []
    async with api.services.db.session() as session:
        chunks = (
            await session.execute(text("SELECT count(*) FROM fingerprint_chunks"))
        ).scalar_one()
    assert chunks == 0


async def test_documents_in_word_and_pdf_and_refused_files(
    api: Api, analyst: dict[str, str]
) -> None:
    for name, content in (
        ("msa.docx", docx_bytes(CONTRACT)),
        ("recipe.pdf", pdf_bytes(["Annual budget review for the harbour project"] * 12)),
        (
            "tracker.py",
            b"def position(vessel):\n    return vessel.latitude, vessel.longitude\n" * 8,
        ),
    ):
        response = await api.client.post(
            "/api/protected/documents",
            files={"file": (name, content, "application/octet-stream")},
            data={"label": name, "category": "CLIENT_CONFIDENTIAL", "source": "seeded"},
            headers=analyst,
        )
        assert response.status_code == 200, response.text
        assert response.json()["document"]["source"] == "seeded"
    listed = (
        await api.client.get("/api/protected/documents?source=seeded", headers=analyst)
    ).json()
    assert sorted(document["label"] for document in listed) == [
        "msa.docx",
        "recipe.pdf",
        "tracker.py",
    ]

    for name, content, status, reason in (
        ("big.txt", b"a " * (5 * 1024 * 1024 + 1), 413, "10 MB"),
        ("image.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", 415, "source files"),
        ("empty.txt", b"   \n", 422, "No text"),
        ("broken.pdf", b"%PDF-1.4 not really", 422, "PDF"),
        ("bomb.docx", docx_bomb(60 * 1024 * 1024), 413, "unpacks to more than 50 MB"),
    ):
        refused = await api.client.post(
            "/api/protected/documents",
            files={"file": (name, content, "application/octet-stream")},
            data={"label": name, "category": "CONTRACT"},
            headers=analyst,
        )
        assert refused.status_code == status, refused.text
        assert reason in refused.json()["detail"]
    wrong = await api.client.post(
        "/api/protected/documents",
        files={"file": ("a.txt", b"some text", "text/plain")},
        data={"label": "a label", "category": "PERSON"},
        headers=analyst,
    )
    assert wrong.status_code == 422 and "category" in wrong.json()["detail"]


async def test_embedder_change_marks_uploads_stale_until_uploaded_again(
    api: Api, analyst: dict[str, str]
) -> None:
    files = {"file": ("msa.txt", CONTRACT.encode(), "text/plain")}
    data = {"label": "MSA Zephyros", "category": "CONTRACT"}
    first = await api.client.post(
        "/api/protected/documents", files=files, data=data, headers=analyst
    )
    async with api.services.db.session() as session:
        await session.execute(
            text("UPDATE protected_documents SET embedder_id = 'openai:older-model'")
        )
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()

    summary = (await api.client.get("/api/protected/summary", headers=analyst)).json()
    assert summary["stale_documents"] == 1
    paste = f"Summarise: {excerpt(CONTRACT, 60, 110)}"
    assert (await _test(api, analyst, paste))["categories"] == []

    second = await api.client.post(
        "/api/protected/documents", files=files, data=data, headers=analyst
    )
    assert second.json()["duplicate"] is False
    assert second.json()["document"]["id"] != first.json()["document"]["id"]
    summary = (await api.client.get("/api/protected/summary", headers=analyst)).json()
    assert summary["stale_documents"] == 0
    assert len((await _test(api, analyst, paste))["categories"]) == 1


@respx.mock
async def test_remove_demo_data_leaves_a_default_only_install(
    api: Api, analyst: dict[str, str]
) -> None:
    respx.get("http://mcp-crm:9001/export/clients").mock(
        return_value=httpx.Response(200, json=CLIENTS)
    )
    await api.client.post("/api/protected/terms/sync", headers=analyst)
    await api.client.post(
        "/api/protected/terms?source=seeded", json=[{"term": "Notos Lines"}], headers=analyst
    )
    await api.client.post("/api/protected/terms", json=[{"term": "Boreas Energy"}], headers=analyst)
    await api.client.post(
        "/api/protected/patterns?source=seeded",
        json={"name": "project code", "regex": r"PRJ-[0-9]{4}", "data_type": "PROJECT"},
        headers=analyst,
    )
    await api.client.post(
        "/api/protected/documents",
        files={"file": ("msa.txt", CONTRACT.encode(), "text/plain")},
        data={"label": "MSA Zephyros", "category": "CONTRACT", "source": "seeded"},
        headers=analyst,
    )
    removed = await api.client.post("/api/protected/demo-data/remove", headers=analyst)
    assert removed.json() == {"terms": 4, "documents": 1, "patterns": 1}

    prompt = "Notos Lines, Zephyros Maritime, PRJ-0042 and Boreas Energy"
    from_stores = [found for found in _types(await _test(api, analyst, prompt)) if found[1]]
    assert from_stores == [("CLIENT", "uploaded")]
    assert "PROJECT" not in api.services.protected.data_types()


async def test_a_second_worker_reloads_on_the_bus_message(
    api: Api, analyst: dict[str, str]
) -> None:
    """Another gateway process on the same database picks a change up without a restart."""
    other = create_app(api.services.settings)
    async with other.router.lifespan_context(other):
        detector = other.state.services.detector
        prompt = "offer for Boreas Energy"

        async def client_found() -> bool:
            findings = (await detector.detect_local(prompt)).findings
            return [finding.data_type for finding in findings] == [DataType.CLIENT]

        assert not await client_found()
        await api.client.post(
            "/api/protected/terms", json=[{"term": "Boreas Energy"}], headers=analyst
        )
        for _ in range(50):
            if await client_found():
                break
            await asyncio.sleep(0.1)
        assert await client_found()
