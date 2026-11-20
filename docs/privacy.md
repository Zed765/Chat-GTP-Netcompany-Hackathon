# Privacy by design

A.S.P.I.D.A. inspects what employees send to AI tools. A tool like that can easily become
the biggest store of sensitive text in the company, and a way to watch individuals. This
document explains how the design avoids both.

It is design rationale written by engineers. **It is not legal advice.** A company that
deploys this must do its own assessment with its data protection officer.

## 1. What is stored, and what never is

| Data | Stored? | Where, and for how long |
| --- | --- | --- |
| Raw prompts, raw responses, raw tool results | Never | Held in memory while a request is processed |
| Secrets (keys, tokens, passwords) | Never | Replaced one way with `<SECRET_REDACTED>`; not even the vault holds them |
| Real values behind placeholders | Encrypted, briefly | Redis, AES-GCM, deleted after 24 hours or when the conversation ends. Redis runs with persistence off, so the vault never reaches a disk |
| Events | Yes | Postgres, 90 days by default. Time, a user pseudonym, team, AI tool, channel, action, rule, policy version, the kinds of data found with counts, timings, cost |
| Masked snippet | Optional | At most 200 characters of the prompt with placeholders in place of every value found, and only when something was found |
| Document fingerprints | Yes | Embedding vectors with a label and a category. The document's text is discarded after embedding and uploads are never written to disk |
| Protected terms (client names and the like) | Encrypted | Postgres, AES-GCM with the vault key; decrypted only in memory |

The code enforces this rather than promising it. The event writer's record type has no
field that could hold a prompt. The per-request trace that powers the "what you typed,
what the AI tool saw" view is returned to the caller and never stored. Tests check that
nothing the fake AI tools received, and nothing in Postgres or Redis, contains a real
value.

## 2. Data minimisation

- **Detect locally, send masked.** Identifiers, names and protected terms are found and
  replaced on the gateway (tiers T0 and T1) before any model is involved. Embeddings and
  the classification model (tiers T2 and T3) only ever receive masked text.
- **Count, do not copy.** An event records that a prompt contained "2 × AFM, 1 × IBAN",
  not the numbers.
- **Teams, not people.** Monitor and questions in plain language work at team level. The
  database views a question can query contain no user column at all, and a team with fewer
  than three active users is shown as "Other" so that a team of one cannot be singled out.
- **Pseudonyms.** Events carry an HMAC of the user ID. The key is kept in a volume
  outside the database, so a copy of the database alone links no event to a person.
  Pseudonymised data is still personal data; the point is to make casual and accidental
  identification impossible. Deliberate identification by an admin stays possible, and
  in this prototype it leaves no trace (section 3).

## 3. Looking at an individual

Sometimes a security team must know who is behind an event, for example when the same
person keeps sending client contracts to an unapproved tool. An admin can look that up
for **one** event at a time, from the events list on the Monitor page.

**Nothing records that lookup.** The prototype has a single admin role and no approval
step, and it keeps no record of what an admin does: an admin can identify the sender of
any event, one at a time, and nobody can see afterwards that it happened. The same holds
for an admin's changes to the protected data, the tool statuses, the directory and the
retention period; only policy versions name their author. This is a simplification of
the prototype and a real gap. A production deployment needs an audit trail of every
lookup and change, kept where an admin cannot alter it, and an approval by a second
person in front of the lookup.

## 4. Retention and transparency

- Events are deleted after 90 days by default. An admin sets the period under Configure,
  "Keep events for", and a daily job enforces it.
- The vault expires after 24 hours and can be ended at once with the conversation.
- The gateway can tell an employee what is inspected and kept (`/api/privacy/notice`) and
  list everything held about them (`/api/privacy/my-data`). The web app shows neither at
  the moment; a deployment would have to.

## 5. The monitoring trade-off under GDPR

Inspecting employees' prompts is monitoring of workers, which European data protection
law treats with care. The design choices above map to the principles a deployer would
have to show:

| Principle | How the design supports it |
| --- | --- |
| Lawfulness and purpose limitation | The purpose is narrow: stop client and personal data leaving through AI tools. In an employment relationship consent is rarely valid, so a deployer would more likely rely on legitimate interests or a legal obligation, with a documented balancing test. Nothing in the product scores or ranks individuals |
| Data minimisation and storage limitation | Sections 1, 2 and 4 |
| Transparency | The notice and the per-user record the gateway serves through its API, which the web app does not show yet; national rules may also require informing or consulting employee representatives |
| Data protection by design and by default | Masking is the default action; identity is off by default and only an admin can look it up |
| Security of processing | Encryption of the vault and of protected terms, a read-only database role for the queries that answer questions, signed sessions with server-side role checks, non-root containers |
| Accountability | Policy versions with their author, and the rule and policy version on every event. What an admin looks up or changes is not recorded, so a deployer has to add an audit trail before it can show this principle in full |

A product that masks instead of blocking is also the less intrusive measure: the employee
keeps working, and less of what they wrote is retained than with a classic DLP quarantine
that keeps the full offending message for review.

## 6. Outline data protection impact assessment

Systematic monitoring of employees is a typical trigger for a DPIA. An outline for a
deployer to complete:

| Part | Starting point |
| --- | --- |
| Description | Inline inspection of prompts to AI tools and of agent tool traffic; pseudonymous events; team-level reporting |
| Necessity and proportionality | Compare with the alternatives: blocking all AI tools (more restrictive, pushes use to private devices), no control (uncontrolled disclosure of client data), log-only DLP (keeps more text) |
| Risks to employees | Feeling watched; identification through small teams or unusual behaviour; misuse of identity lookups; retention longer than needed; false positives that expose what someone was working on |
| Measures | Sections 1 to 4; small-team folding; configurable retention; masked snippets can be switched off |
| Residual risk | An admin can look up who sent any event and nothing records it, so misuse of the lookup cannot be detected until an audit trail and an approval step are added. Administrators with access to both the database and the key volume can re-identify users; this is an organisational control (separation of duties), not a technical one |
| Consultation | Data protection officer; employee representatives where national law requires it |

## 7. Model providers and data residency

- Every call to a model that carries what employees or tools wrote carries masked text
  only: the classification model, the embedding model and the stand-ins for public AI tools
  in the demo all see placeholders.
- What an admin types for the model goes as written: an instruction for a policy rule, a
  question about usage, and a description of a format to write a pattern for.
- Requests are sent with storage disabled where the API allows it.
- OpenAI documents EU data residency for GPT-6 Luna and the embedding models (an EU
  project and the `https://eu.api.openai.com/v1` endpoint). Set `OPENAI_BASE_URL` to use
  it. Detection of identifiers, names and protected terms is local; document fingerprints
  and categories use the models.

## 8. Where the EU AI Act is relevant

- **The gateway as a governance tool.** The Act expects organisations that use AI systems
  to know which they use and to use them responsibly, including staff AI literacy. The
  inventory, the discovery of unapproved tools and the policy give a deployer the facts
  it needs.
- **The gateway itself.** It uses machine learning (named-entity recognition, embeddings,
  a language model) on workers' activity. AI systems used to monitor or evaluate workers
  can fall under the Act's high-risk category for employment. The design keeps clear of
  evaluating people: no individual scores, team-level reporting, identity only through
  an admin's lookup of one event, which the prototype does not record. A deployer that
  repurposed the events for performance management would change that assessment, and
  should not.
- **The in-house agent.** Users are told they are talking to an AI system, and its tool
  calls are visible in the trace.

Applicability dates and guidance under the Act are still moving; check the current state
before relying on any of this.
