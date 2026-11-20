"""Where synced terms come from. The mock CRM is the one implementation shipped; a
connector to a real CRM implements the same protocol."""

from typing import Any, Protocol

import httpx

from gateway.app.core.types import DataType
from gateway.app.protected.errors import SourceUnavailableError

CRM_TIMEOUT_S = 10.0
CLIENT_GROUP = "crm-clients"
CONTACT_GROUP = "crm-contacts"


class TermSource(Protocol):
    async def fetch(self) -> list[dict[str, Any]]:
        """Rows with `term`, `aliases`, `data_type` and `group`, validated by the importer."""
        ...


def terms_from_clients(clients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each client becomes a `CLIENT` term with its other names as aliases. A contact
    person is client data as well, so each one is a `CLIENT` term of its own: a prompt
    that names only the contact still counts as client data for the policy and reports."""
    rows: list[dict[str, Any]] = []
    for client in clients:
        names = [client.get("legal_name"), client.get("trade_name"), *client.get("aliases", [])]
        distinct = list(dict.fromkeys(name for name in names if isinstance(name, str) and name))
        if distinct:
            rows.append(
                {
                    "term": distinct[0],
                    "aliases": distinct[1:],
                    "data_type": DataType.CLIENT,
                    "group": CLIENT_GROUP,
                }
            )
        rows += [
            {
                "term": contact.get("name"),
                "aliases": [],
                "data_type": DataType.CLIENT,
                "group": CONTACT_GROUP,
            }
            for contact in client.get("contacts", [])
        ]
    return rows


class CrmTermSource:
    """Reads the CRM's client export over HTTP."""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = f"{base_url.rstrip('/')}/export/clients"
        self._transport = transport

    async def fetch(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(
                timeout=CRM_TIMEOUT_S, transport=self._transport
            ) as client:
                response = await client.get(self._url)
                response.raise_for_status()
                clients = response.json()
        except (httpx.HTTPError, ValueError) as problem:
            raise SourceUnavailableError("The CRM did not answer the client export") from problem
        if not isinstance(clients, list):
            raise SourceUnavailableError("The CRM's client export is not a list")
        return terms_from_clients([client for client in clients if isinstance(client, dict)])
