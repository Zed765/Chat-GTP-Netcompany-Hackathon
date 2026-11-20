"""The default pack's category exemplars: fingerprinted at start, kept current, switchable."""

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from gateway.app.config import Settings
from gateway.tests.conftest import REPO, TEST_REDIS, Api, running_gateway
from gateway.tests.doubles import FakeLLM
from gateway.tests.protected.conftest import ADMIN
from gateway.tests.protected.helpers import EXEMPLARS, RESEMBLES_A_CONTRACT

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_stores")]


@pytest.fixture
def defaults_dir(tmp_path: Path) -> Path:
    """A copy of the real default pack, with a handful of invented exemplars."""
    directory = tmp_path / "defaults"
    exemplars = directory / "exemplars"
    exemplars.mkdir(parents=True)
    for name in ("terms.yaml", "patterns.yaml", "tools.yaml"):
        shutil.copy(REPO / "defaults" / name, directory / name)
    manifest = []
    for name, category, language, body in EXEMPLARS:
        (exemplars / f"{name}.txt").write_text(body, encoding="utf-8")
        manifest.append(
            {"id": name, "file": f"{name}.txt", "category": category, "language": language}
        )
    (exemplars / "manifest.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in manifest), encoding="utf-8"
    )
    return directory


@pytest.fixture
async def api(
    settings: Settings, database_url: str, defaults_dir: Path, llm: FakeLLM
) -> AsyncIterator[Api]:
    wired = settings.model_copy(
        update={
            "database_url": database_url,
            "redis_url": TEST_REDIS,
            "defaults_dir": defaults_dir,
        }
    )
    async with running_gateway(wired, llm) as running:
        yield running


async def _exemplar_ids(api: Api) -> dict[str, str]:
    response = await api.client.get(
        "/api/protected/documents?source=default", headers=api.as_(ADMIN)
    )
    return {document["label"]: document["id"] for document in response.json()}


async def _categories(api: Api, prompt: str) -> list[tuple[str, str, bool, str]]:
    response = await api.client.post(
        "/api/protected/test", json={"text": prompt}, headers=api.as_(ADMIN)
    )
    return [
        (found["category"], found["tier"], found["conclusive"], found["evidence"])
        for found in response.json()["categories"]
    ]


async def test_exemplars_are_fingerprinted_once_and_classify_by_resemblance(
    api: Api, llm: FakeLLM
) -> None:
    ids = await _exemplar_ids(api)
    assert sorted(ids) == sorted(name for name, *_ in EXEMPLARS)
    # A resemblance is not conclusive, so the model is asked, and here it does not answer.
    llm.answers["CategoryVerdict"] = TimeoutError("slow")
    assert await _categories(api, RESEMBLES_A_CONTRACT) == [
        ("CONTRACT", "T2", False, "resembles a contract")
    ]
    assert len(llm.asked) == 1
    summary = (await api.client.get("/api/protected/summary", headers=api.as_(ADMIN))).json()
    fingerprints = next(store for store in summary["stores"] if store["store"] == "fingerprints")
    assert {group["group"] for group in fingerprints["groups"]} == {
        "CONTRACT", "SOURCE_CODE", "BENIGN"
    }  # fmt: skip
    assert "BENIGN" not in summary["data_types"]

    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    assert await _exemplar_ids(api) == ids


async def test_exemplars_are_fingerprinted_again_when_they_or_the_embedder_change(
    api: Api, defaults_dir: Path
) -> None:
    ids = await _exemplar_ids(api)
    (defaults_dir / "exemplars" / "benign-en-01.txt").write_text(
        "A different everyday request about booking a meeting room for Tuesday.", "utf-8"
    )
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    changed = await _exemplar_ids(api)
    assert sorted(changed) == sorted(ids) and set(changed.values()).isdisjoint(ids.values())

    async with api.services.db.session() as session:
        await session.execute(
            text("UPDATE protected_documents SET embedder_id = 'openai:older-model'")
        )
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    documents = (
        await api.client.get("/api/protected/documents?source=default", headers=api.as_(ADMIN))
    ).json()
    assert len(documents) == len(EXEMPLARS)
    assert {document["embedder_id"] for document in documents} == {"openai:text-embedding-3-large"}
    assert not any(document["stale"] for document in documents)


async def test_exemplar_group_can_be_switched_off(api: Api) -> None:
    off = await api.client.patch(
        "/api/protected/groups/fingerprints/CONTRACT",
        json={"enabled": False},
        headers=api.as_(ADMIN),
    )
    assert off.status_code == 200
    assert await _categories(api, RESEMBLES_A_CONTRACT) == []

    async with api.services.db.session() as session:
        await session.execute(text("UPDATE protected_documents SET pack_version = 'older'"))
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    assert await _categories(api, RESEMBLES_A_CONTRACT) == []
    documents = (
        await api.client.get("/api/protected/documents?source=default", headers=api.as_(ADMIN))
    ).json()
    assert {doc["enabled"] for doc in documents if doc["category"] == "CONTRACT"} == {False}


async def test_a_pack_without_exemplars_is_fine(api: Api, defaults_dir: Path) -> None:
    shutil.rmtree(defaults_dir / "exemplars")
    await api.services.protected.load_default_pack()
    await api.services.protected.reload()
    assert await _exemplar_ids(api) == {}
    assert await _categories(api, RESEMBLES_A_CONTRACT) == []
