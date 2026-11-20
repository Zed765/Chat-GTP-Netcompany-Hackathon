# Contracts

How the parts of A.S.P.I.D.A. talk to each other. Change a contract only with the
orchestrator's agreement, because every workstream builds against it.

## Between the gateway modules (Python)

| File | Holds |
| --- | --- |
| `gateway/app/core/types.py` | Every model that crosses a module boundary: `Finding`, `MaskResult`, `PolicyContext`, `PolicyDecision`, `Explanation`, `InjectionVerdict`, the enums |
| `gateway/app/core/interfaces.py` | The protocols the prompt pipeline calls: `Detector`, `Vault`, `Rehydrator`, `PolicyService`, `Inventory`, `InjectionDetector` |
| `gateway/app/core/deps.py` | `Deps`: what every module's `build` function receives (settings, keys, database, Redis, reload bus, model client, directory) |
| `gateway/app/core/textnorm.py` | Greek-aware normalisation: `fold`, `transliterate`, `entity_key`. Used by the term matcher and by the vault's entity linking, so both link "Μαρίας" and "Maria" the same way |
| `gateway/app/core/services.py` | `Services`: the built modules, reachable in a route through the `Svc` dependency |

Each module exposes `async def build(deps, ...)` in its `__init__.py` and returns the class
named there (`DetectionService`, `VaultService`, `PolicyEngine`, `InventoryService`,
`InjectionService`, `ProtectedData`). Keep those names and signatures; add methods freely.

Rules that hold everywhere:

- **No raw text is stored or logged.** Prompts, responses, tool results and matched values
  live in memory only. Events go through `EventWriter`, whose record has no field for text
  beyond a masked snippet of at most 200 characters. Never log a finding's `text`.
- **Offsets index the original text.** `Finding.start` and `Finding.end` refer to the exact
  string given to `detect_local`, so the UI can highlight what the user typed.
- **Only inspected text is forwarded.** `gateway/app/proxy/payload.py` lists every text of
  a request and the control fields that may pass; anything else is refused. A new request
  field has to be added there, as inspected text or as a control field, before the
  gateway will forward it.
- **Model calls go through `deps.llm`** (`gateway/app/llm/client.py`). What an employee or
  a tool wrote may be sent only masked. What an admin types for the model (an instruction
  for a rule, a question, a format to write a pattern for) goes as written. Tests put a
  double in its place (`gateway/tests/doubles.py`), so a test scripts the answer of every
  model call it causes.
- **Changes reload without a restart.** After changing a store, call
  `await deps.bus.publish("<topic>")`; subscribe your reload function in `build`.
  Topics: `policy`, `protected`, `inventory`, `directory`, `privacy`, `agent-trust`.
- **Teams come from the directory.** `deps.directory.team_of(user_id=..., ip=...)` resolves
  a log line or a user to a team; it answers `Unknown` when it cannot.
- **Events say where they came from.** `origin` is `gateway` (inspected in the path) or
  `log` (seen in an activity log). `forwarded` is false for a block or an unconfirmed
  warning. The view `v_events` adds `sent_unmasked`: the text reached the AI tool as
  written.
- **Authorisation** comes from `gateway/app/core/auth.py`: `CurrentPrincipal` for anyone
  signed in and `Admin`. Every route except health, meta and demo sign-in needs one.

Each module owns the tables in its own `models.py`. The orchestrator regenerates
`gateway/migrations/versions/0001_initial_schema.py` from the models when workstreams merge;
hand-written SQL (views, roles) lives in `0002`.

## For the web app (HTTP)

- `contracts/gateway.openapi.json`: everything under `/api` and `/v1`.
- `contracts/agent.openapi.json`: the agent service, served under `/agent-api`.

Both are generated: run `make contracts` after changing a route or schema, and commit the
result. The request and response models live next to each router in `schemas.py`.

Notes the OpenAPI files cannot express:

- `POST /v1/chat/completions` is OpenAI-compatible. The gateway reads three extra headers:
  `X-Aspida-Tool` (inventory slug or domain of the destination AI tool),
  `X-Aspida-Conversation` (any stable ID; scopes the vault) and
  `X-Aspida-Acknowledge-Warning: <trace_id of the warning or the block>` (send the masked
  version after a warning or a block).
- `POST /v1/responses` is the OpenAI Responses API through the same path, for the in-house
  agent. It is stateless (send the whole `input`, no `previous_response_id`). Assistant
  text comes back restored; function-call arguments keep their placeholders. The decision
  is in the `X-Aspida-Action`, `X-Aspida-Rule` and `X-Aspida-Trace-Id` response headers.
- Block answers 403 and warn answers 409, both with a `PolicyErrorResponse` body.
- When streaming, the first chunk carries `aspida` (a `Trace`) and the last chunk before
  `[DONE]` carries `aspida_summary` (a `TraceSummary`); both have empty `choices`.
- The agent's `POST /sessions/{id}/messages` answers with server-sent events; each `data:`
  line is one `AgentEvent`. The agent asks for the model the gateway names in `live_model`
  of the agent session.

## Files shared between workstreams

| File | Written by | Read by | Shape |
| --- | --- | --- | --- |
| `seeder/data/world.json` | `seeder/world.py` | seeder, eval, examples | `organisation {name, domain}`, `teams [{name, cidr}]`, `employees [{user_id, display_name, team, ip}]`, `clients [...]`, `projects [{code, name, team}]` |
| `seeder/data/clients.json` | `seeder/world.py` | `mcp-crm`, eval | A list of `{id, kind: company or individual, legal_name, trade_name, aliases [..], contacts [{name, role, email, phone}], afm, iban, email, phone, address, team, language}` |
| `seeder/site_descriptions.json` | data workstream | discovery | `{"<domain>": {"title": "...", "description": "..."}}` |
| `defaults/terms.yaml`, `defaults/patterns.yaml` | detection workstream | `gateway/app/protected` | Defined by the loader; documented in the files |
| `defaults/tools.yaml` | discovery workstream | `gateway/app/discovery` | The catalogue of AI tools, including the three fictional ones |
| `defaults/exemplars/` | data workstream | `gateway/app/protected` | Text files plus `manifest.jsonl` with `{id, file, category, language}` |
| `defaults/examples.json` | data workstream | `GET /api/examples` | A list of `Example` (see `gateway/app/proxy/schemas.py`) for the Chat page |

The mock CRM also serves `GET /export/clients` (the content of `clients.json`), which is
what the gateway's CRM `TermSource` reads.

The three fictional AI tools on the Chat page are `athena-assist` (approved), `draftpilot`
(tolerated) and `chatterbox-ai` (unapproved). `mock-upstream` serves each under
`/tools/<slug>/v1/chat/completions`, answers with the model, and lists everything it
received at `GET /recordings` (`DELETE /recordings` clears it). The agent's own model is the inventory tool
`company-assistant` (approved): the gateway forwards it to OpenAI with its own key.

Log formats for discovery: Squid native `access.log`
(`time.ms elapsed client code/status bytes method URL user hierarchy/peer type`, with the
user ID in the user field) and a DNS query log with one `ISO-timestamp client-ip qname qtype`
per line.

## Demo organisation

Six teams: Sales, Legal, Finance, Engineering, HR, Customer Support. The three demo sign-in
users are in `gateway/app/core/auth.py`; the employee belongs to Sales. Everything else about
the organisation comes from `seeder/data/world.json`.
