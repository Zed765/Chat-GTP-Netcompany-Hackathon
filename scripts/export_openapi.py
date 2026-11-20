"""Write the OpenAPI contracts the web app is built against: `make contracts`."""

import json
from pathlib import Path

from agent.main import app as agent_app
from gateway.app.main import app as gateway_app

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"

for name, app in (("gateway", gateway_app), ("agent", agent_app)):
    path = CONTRACTS / f"{name}.openapi.json"
    path.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(CONTRACTS.parent)}")
