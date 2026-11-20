"""A small client for the gateway APIs the seeder loads the demo organisation through."""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx

from seeder.activity.profiles import Tool

log = logging.getLogger("seeder.gateway")

RETRY_STATUSES = frozenset({502, 503, 504})
ATTEMPTS = 5


class GatewayError(RuntimeError):
    """A request the gateway refused. The message never includes a request or response body,
    because a validation error echoes what was sent, and that can be a prompt."""


class Gateway:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=120.0, transport=transport)
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def wait_until_ready(self, seconds: float) -> None:
        """Poll the health check while the gateway is still starting."""
        deadline = time.monotonic() + seconds
        while True:
            try:
                if self._http.get("/healthz").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            if time.monotonic() >= deadline:
                raise GatewayError(f"the gateway was not healthy after {seconds:.0f} seconds")
            self._sleep(2.0)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                failure = type(exc).__name__
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRY_STATUSES:
                    raise GatewayError(f"{method} {path} answered {response.status_code}")
                failure = f"status {response.status_code}"
            if attempt < ATTEMPTS:
                log.warning("%s %s failed (%s); retrying", method, path, failure)
                self._sleep(2.0 * attempt)
        raise GatewayError(f"{method} {path} failed {ATTEMPTS} times ({failure})")

    def sign_in(self, user_id: str) -> None:
        session = self._request("POST", "/api/demo/login", json={"user_id": user_id}).json()
        self._http.headers["Authorization"] = f"Bearer {session['token']}"

    def seed_state(self) -> set[str]:
        return set(self._request("GET", "/api/demo/seed-state").json())

    def mark(self, step: str) -> None:
        self._request("PUT", f"/api/demo/seed-state/{step}")

    def import_directory(
        self, users: Sequence[Mapping[str, str]], networks: Sequence[Mapping[str, str]]
    ) -> None:
        body = {"users": list(users), "networks": list(networks)}
        self._request("POST", "/api/directory", params={"source": "seeded"}, json=body)

    def sync_terms(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", "/api/protected/terms/sync").json()
        return result

    def upload_document(self, filename: str, content: bytes, label: str, category: str) -> bool:
        """Fingerprint one document. Returns whether the gateway already had it."""
        response = self._request(
            "POST",
            "/api/protected/documents",
            files={"file": (filename, content, "text/plain")},
            data={"label": label, "category": category, "source": "seeded"},
        )
        return bool(response.json()["duplicate"])

    def pattern_names(self) -> set[str]:
        rows = self._request("GET", "/api/protected/patterns", params={"source": "seeded"}).json()
        return {row["name"] for row in rows}

    def add_pattern(self, name: str, regex: str, data_type: str) -> None:
        body = {"name": name, "regex": regex, "data_type": data_type}
        self._request("POST", "/api/protected/patterns", params={"source": "seeded"}, json=body)

    def tools(self) -> list[Tool]:
        return [
            Tool(slug=row["slug"], status=row["status"], domains=tuple(row["domains"]))
            for row in self._request("GET", "/api/tools").json()
        ]

    def upload_log(self, filename: str, content: str, kind: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/api/discovery/logs",
            files={"file": (filename, content.encode(), "text/plain")},
            data={"kind": kind},
        )
        result: dict[str, Any] = response.json()
        return result

    def ingest_prompts(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST", "/api/ingest/prompts", json=list(records)
        ).json()
        return result
