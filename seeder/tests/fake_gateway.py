"""A stand-in for the gateway's seeding APIs, shaped like `contracts/gateway.openapi.json`."""

import json
import re
from typing import Any

import httpx

from seeder.activity.profiles import Tool

ADMIN = "a.bilas"
INVENTORY = (
    Tool("athena-assist", "approved", ("athena-assist.example",)),
    Tool("draftpilot", "tolerated", ("draftpilot.example",)),
    Tool("chatterbox-ai", "unapproved", ("chatterbox-ai.example",)),
    Tool("company-assistant", "approved", ()),
    Tool("chatgpt", "unapproved", ("chatgpt.com", "chat.openai.com")),
    Tool("perplexity", "unapproved", ("perplexity.ai",)),
    Tool("cursor", "unapproved", ("cursor.com",)),
    Tool("quillbot", "unapproved", ("quillbot.com",)),
    Tool("claude", "tolerated", ("claude.ai",)),
    Tool("grammarly", "tolerated", ("grammarly.com",)),
    Tool("github-copilot", "approved", ("githubcopilot.com",)),
    Tool("microsoft-365-copilot", "approved", ("m365.cloud.microsoft",)),
    Tool("deepl", "approved", ("deepl.com",)),
)


def _field(body: bytes, name: str) -> str:
    match = re.search(rb'name="%b"\r\n\r\n(.*?)\r\n--' % name.encode(), body, re.DOTALL)
    assert match, f"the form has no field {name}"
    return match[1].decode()


def _filename(body: bytes) -> str:
    match = re.search(rb'filename="([^"]+)"', body)
    assert match
    return match[1].decode()


class FakeGateway:
    """Records what the seeder loads. `unhealthy` health checks fail first; `broken` is a path
    that always answers 500."""

    def __init__(self, *, unhealthy: int = 0, broken: str | None = None) -> None:
        self.unhealthy = unhealthy
        self.broken = broken
        self.requests: list[str] = []
        self.sign_ins: list[str] = []
        self.steps: list[str] = []
        self.directory: dict[str, Any] = {}
        self.term_syncs = 0
        self.documents: list[dict[str, str]] = []
        self.patterns: list[dict[str, str]] = []
        self.logs: list[dict[str, str]] = []
        self.batches: list[list[dict[str, Any]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(f"{request.method} {path}")
        if path == "/healthz":
            self.unhealthy -= 1
            return httpx.Response(503 if self.unhealthy >= 0 else 200, json={"status": "ok"})
        if path == self.broken:
            return httpx.Response(500, json={"detail": "broken on purpose"})
        if path == "/api/demo/login":
            user_id = json.loads(request.content)["user_id"]
            assert user_id == ADMIN
            self.sign_ins.append(user_id)
            return httpx.Response(200, json={"token": f"session-of-{user_id}", "user": {}})
        user_id = request.headers.get("Authorization", "").removeprefix("Bearer session-of-")
        if user_id != ADMIN:
            return httpx.Response(401, json={"detail": "Sign in first"})
        return self._authorised(request, path)

    def _authorised(self, request: httpx.Request, path: str) -> httpx.Response:
        body = request.content
        seeded = request.url.params.get("source") == "seeded"
        if path == "/api/demo/seed-state":
            return httpx.Response(200, json=self.steps)
        if path.startswith("/api/demo/seed-state/"):
            self.steps.append(path.rsplit("/", 1)[1])
            return httpx.Response(204)
        if path == "/api/directory":
            assert seeded
            self.directory = json.loads(body)
            return httpx.Response(204)
        if path == "/api/protected/terms/sync":
            self.term_syncs += 1
            return httpx.Response(200, json={"imported": 180, "duplicates": 0, "errors": []})
        if path == "/api/protected/documents":
            row = {key: _field(body, key) for key in ("label", "category", "source")}
            duplicate = any(document["label"] == row["label"] for document in self.documents)
            if not duplicate:
                self.documents.append({**row, "filename": _filename(body)})
            return httpx.Response(200, json={"document": {}, "duplicate": duplicate})
        if path == "/api/protected/patterns" and request.method == "GET":
            return httpx.Response(200, json=self.patterns)
        if path == "/api/protected/patterns":
            assert seeded
            self.patterns.append(json.loads(body))
            return httpx.Response(200, json=self.patterns[-1])
        if path == "/api/tools":
            rows = [
                {"slug": tool.slug, "status": tool.status, "domains": list(tool.domains)}
                for tool in INVENTORY
            ]
            return httpx.Response(200, json=rows)
        if path == "/api/discovery/logs":
            self.logs.append({"kind": _field(body, "kind"), "body": body.decode()})
            result = {"lines": body.count(b"\n"), "matched": 1, "new_tools": 7}
            return httpx.Response(200, json=result)
        if path == "/api/ingest/prompts":
            records = json.loads(body)
            assert len(records) <= 200
            self.batches.append(records)
            return httpx.Response(200, json={"ingested": len(records), "actions": {"allow": 1}})
        return httpx.Response(404, json={"detail": "Not found"})

    @property
    def prompts(self) -> list[dict[str, Any]]:
        return [record for batch in self.batches for record in batch]
