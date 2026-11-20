import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mock_upstream.main import app
from mock_upstream.settings import MissingKeyError, Settings
from mock_upstream.tests.fakes import OPENING, FakeOpenAI, fake_model

client = TestClient(app)
PROMPT = "Reply to <PERSON_1> about tax number <AFM_1> and account <IBAN_1>."


@pytest.fixture(autouse=True)
def model() -> Iterator[FakeOpenAI]:
    with fake_model() as fake:
        yield fake


def _ask(tool: str, content: str, *, stream: bool = False) -> tuple[int, str]:
    body = {"model": "m", "messages": [{"role": "user", "content": content}], "stream": stream}
    response = client.post(f"/tools/{tool}/v1/chat/completions", json=body)
    return response.status_code, response.text


@pytest.mark.parametrize("tool", ["athena-assist", "draftpilot", "chatterbox-ai"])
def test_a_demo_tool_answers_with_the_model_and_records_what_it_received(
    tool: str, model: FakeOpenAI
) -> None:
    client.delete("/recordings")
    status, text = _ask(tool, PROMPT)
    assert status == 200
    assert json.loads(text)["choices"][0]["message"]["content"] == OPENING + PROMPT
    (request,) = model.requests
    assert request["input"] == [{"role": "user", "content": PROMPT}]
    assert (request["model"], request["store"]) == ("gpt-6-luna", False)
    (recording,) = client.get("/recordings", params={"tool": tool}).json()
    assert recording["body"]["messages"][0]["content"] == PROMPT


def test_stream_splits_the_same_text_into_small_chunks(model: FakeOpenAI) -> None:
    _, text = _ask("echo", PROMPT, stream=True)
    lines = [line[6:] for line in text.splitlines() if line.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    pieces = [json.loads(line)["choices"][0]["delta"].get("content", "") for line in lines[:-1]]
    assert "".join(pieces) == PROMPT
    assert max(len(piece) for piece in pieces) <= 5
    assert model.requests == [], "the echo tool asks no model"


def test_unknown_tool_is_rejected() -> None:
    assert _ask("not-a-tool", "hi")[0] == 404


def test_a_key_is_required() -> None:
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY is required"):
        Settings(OPENAI_API_KEY=None)
    assert Settings(OPENAI_API_KEY="k").api_key == "k"
