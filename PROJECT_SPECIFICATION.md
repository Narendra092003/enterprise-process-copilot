# Enterprise Process Automation & Copilot Assistant — Project Specification (v2, buildable)

**Source of truth** for scope, rules and acceptance criteria. The numbered guides in [`docs/`](./docs/00-README.md) explain how; this file says what. [`DESIGN-CHANGES.md`](./DESIGN-CHANGES.md) lists what changed from the original 22-document specification and why.

**Status language.** The `app/` folder in this package is a **reference implementation**. Its core logic was run and tested while preparing the package (19 core tests, evaluation in offline mode). The FastAPI layer, Pinecone calls, Copilot Studio topics and Power Automate flows are written to the official documentation but **were not run in the preparation environment**. They are verified only when you run them. Portfolio claims are allowed only after that evidence exists (Section 9).

## 1. Product goal

Employees ask routine operational questions (access, leave, expenses, IT fixes, onboarding) that are already answered in internal documents. Build an assistant that:

- answers **only** from approved documents, with a citation for every answer;
- respects who is allowed to read what;
- says "not in the approved documents" instead of guessing;
- resists prompt injection from users and from documents;
- starts one routine action (an access request) only after explicit user confirmation and manager approval.

## 2. MVP scope

### In scope
- Python 3.11+ FastAPI retrieval API with API-key auth mapped to groups.
- Ingestion of PDF, DOCX, TXT and Markdown: parsing, section-aware chunking, embeddings, Pinecone upsert.
- Pinecone serverless index with metadata: groups, lifecycle, version, section, page, flagged.
- SQLite catalog: documents, ingestion jobs, query log (no query text), feedback.
- Prompt-safety filters: input (injection, credential requests, PII redaction, length), evidence (poisoned-chunk flagging), output (secret masking).
- Context-aware response templates: how-to, policy, troubleshoot, contact, general, and fallbacks for no evidence, low confidence and blocked.
- Calibrated abstention threshold (`MIN_SCORE`).
- Copilot Studio agent calling the API (Option A `/v1/answer` topic; Option B custom knowledge topic on `/v1/search`).
- Power Automate Flow B: access request with confirmation, validation, list row and approval.
- Evaluation script, automated tests, metrics endpoint, browser test console.
- 9 synthetic sample documents, including one HR-only document and one poisoned document.

### Out of scope
- Real company documents or a real employer tenant.
- Entra ID per-user tokens, SharePoint permission sync (documented as the upgrade path).
- OCR, malware scanning, hybrid search or reranking, multi-agent orchestration.
- Any high-impact decision (HR, legal, finance, security access) made by the assistant.

## 2a. Stretch goals (only after Section 10 passes)
- Power Automate Flow A/A2: SharePoint file created, changed or deleted → ingestion API (needs the premium HTTP connector).
- Render deployment with an always-on URL.
- Local embeddings (`EMBEDDING_PROVIDER=local`) compared against Pinecone e5 on the same evaluation set.

## 3. User workflow
1. An employee asks a question in Copilot Studio.
2. Copilot sends the question to the API; the API filters, retrieves and checks access, then returns evidence or abstains.
3. Copilot answers with a citation link, or says the documents don't cover it and names the service desk.
4. For an access-request how-to, the agent offers to raise the request, shows a preview and asks Yes/No.
5. On Yes, Flow B validates, creates a request with status *Pending approval*, returns a reference and emails the manager for approval.
6. The employee can rate the answer, and an admin sees metrics.

## 4. Architecture and responsibilities

| Component | Responsibility | Must not |
|---|---|---|
| Copilot Studio | Dialogue, wording, confirmation | Hold Pinecone keys; decide access |
| FastAPI | Auth, safety, retrieval, access filter, catalog re-check, templates, logs | Accept identity or filters from the request body |
| Pinecone | Vector similarity + metadata filter | Be the system of record |
| SQLite catalog | Document lifecycle, versions, jobs, metrics | Store question text |
| Power Automate | Named, validated actions; approvals; source events | Expose a "run any action" tool |

Diagrams: [`docs/01-architecture.md`](./docs/01-architecture.md).

## 5. Retrieval, evidence and safety rules
1. Groups come from the API key on the server. Request models use `extra="forbid"`.
2. Every Pinecone query carries the server-built filter: `allowed_groups $in principal.groups`, `lifecycle = ACTIVE`, `flagged = false`.
3. Every hit is re-checked against the catalog (ACTIVE, current version, group overlap) before serialisation.
4. If the top score is below `MIN_SCORE`, the response is `insufficient_evidence` with no passages. `MIN_SCORE` is set from `scripts/evaluate.py --calibrate`, never guessed.
5. Chunks with instruction-like text are flagged at ingestion and never returned.
6. A user query with injection or credential-request patterns is blocked; PII is redacted before embedding and logging.
7. Secrets in returned text are masked.
8. Delete = mark DELETED in the catalog first, then delete vectors.
9. Same `source_id` + same content hash = `skipped`; a new version replaces the old vectors.
10. One embedding model per index; a dimension mismatch stops startup.

## 6. API contract (summary — full schema at `/docs`)

| Method & path | Who | Purpose |
|---|---|---|
| `GET /health/live`, `GET /health/ready` | platform | liveness / readiness |
| `GET /v1/me` | any key | shows principal + groups |
| `POST /v1/search` `{query, top_k, conversation_id?}` | employee | evidence only: `status`, `evidence[] {title, content, content_location, section, page, score}` |
| `POST /v1/answer` `{query}` | employee | template answer + citations + `suggested_action` |
| `POST /v1/feedback` `{request_id, rating, category}` | owner of request | feedback |
| `POST /v1/ingestion-jobs` (JSON base64) / `POST /v1/documents/upload` (multipart) | admin | 202 + `job_id` |
| `GET /v1/ingestion-jobs/{id}` | admin | job state |
| `GET /v1/documents`, `DELETE /v1/documents/{id}`, `POST /v1/documents/delete-by-source` | admin | catalog |
| `GET /v1/metrics` | admin | self-service rate, abstentions, blocks, PII redactions, latency, feedback |

Statuses: `evidence_found`, `no_evidence`, `insufficient_evidence`, `blocked`.

## 7. Interface requirements
- Copilot Studio test panel: cited answers, an abstention message, a blocked message, and the action preview with Yes/No.
- Browser test console (`/`): employee vs HR identity switch, status and intent tags, feedback buttons.
- Swagger `/docs` with the **Authorize** button for the API key.

## 8. Technical requirements
- Python 3.11+, `requirements.txt`, `.env` (never committed), `.env.example`.
- Pinecone serverless, `multilingual-e5-large` (1024 dimensions, cosine) via Pinecone Inference.
- Offline mode (`memory` + `hash`) must keep working so tests run without accounts.
- Public HTTPS URL (ngrok or Render) with non-default random API keys before connecting Microsoft services.

## 9. Portfolio deliverables
- GitHub repository (no secrets), README with architecture diagram.
- `docs/EVALUATION.md` with **your** measured Pinecone numbers: hit@1, hit@3, abstention accuracy, leakage, safety checks, MIN_SCORE chosen and why.
- Screenshots: cited answer, abstention, access boundary, blocked injection, confirmation + approval.
- A 3–5 minute backup demo video.
- Resume bullets that use only collected measurements ([`docs/09-interview-guide.md`](./docs/09-interview-guide.md)).

## 10. Acceptance criteria
1. `python -m pytest -q` passes.
2. `scripts/evaluate.py` with Pinecone: **0 leaks**, all safety cases pass, abstention on all unanswerable questions, and hit@3 ≥ 90 % on answerable ones (if not, record the actual figure and the reason).
3. Copilot Studio test panel returns a cited answer from your API.
4. A request created through the agent requires Yes, creates exactly one list row, and triggers an approval; "No" creates nothing.
5. Deleting a document removes it from answers immediately.
6. No API key or `.env` in the repository history.

## 11. Repository layout
See [`README.md`](./README.md#folder-map).

## 12. Implementation sequence
Build in the phase order of [`docs/08-build-order.md`](./docs/08-build-order.md). Each phase is small and runnable; finish its "done when" check and the explain-it check, then commit (`Phase N: ...`). The reference implementation in `app/` shows one correct way to finish each phase. Read it, rewrite it in your own words, and change it where you'd do it differently, so that you can explain every line.

## 13. Official technical references
- Copilot Studio custom knowledge sources — https://learn.microsoft.com/microsoft-copilot-studio/guidance/custom-knowledge-sources
- Copilot Studio HTTP request node — https://learn.microsoft.com/microsoft-copilot-studio/authoring-http-node
- Copilot Studio trial sign-up — https://learn.microsoft.com/microsoft-copilot-studio/sign-up-individual
- Pinecone docs (Python SDK, inference, metadata filtering) — https://docs.pinecone.io
- FastAPI — https://fastapi.tiangolo.com
- Power Automate approvals — https://learn.microsoft.com/power-automate/get-started-approvals
