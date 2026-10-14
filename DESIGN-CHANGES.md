# Design Changes (v2, 14 October 2026)

The original package (22 numbered documents) was a production-grade proposal with no code. v2 keeps its architecture and principles: Python returns evidence, access is enforced on the server, abstain rather than guess, documents are data, and actions are confirmed. It shrinks the scope to something one person can build, run and explain by 21 October, and adds a tested reference implementation.

| # | Change | Why | Where |
|---|---|---|---|
| 1 | Added a working reference implementation (`app/`, tests, evaluation, sample documents) | The original package had no code, so no feature claim could be demonstrated | `app/`, `tests/`, `scripts/` |
| 2 | Entra ID tokens → API keys mapped to groups | Entra delegated identity needs tenant admin work; API keys show the same server-side principle | Spec §5; `app/auth.py` |
| 3 | PostgreSQL + Service Bus queue + worker → SQLite + FastAPI background tasks | No Azure subscription needed; the `Catalog` class is the swap point | Spec §2; `app/catalog.py` |
| 4 | SharePoint ACL sync → `allowed_groups` set at ingestion | Graph permission sync is out of scope; the filter and catalog re-check are unchanged | Spec §2, §5 |
| 5 | Embedding provider decided: Pinecone Inference `multilingual-e5-large` (1024 dimensions) | One account, no extra model key; e5 has query/passage input types | `app/embeddings.py`; docs/03 |
| 6 | Added offline mode (`memory` store + `hash` embedder) | Learn and test without accounts or internet; all tests run offline | `app/vectorstore.py`, `app/embeddings.py` |
| 7 | Added `/v1/answer` with context-aware response templates beside `/v1/search` | Backs the resume claim "context-aware response templates"; gives a simple Copilot Option A | `app/templates.py` |
| 8 | Safety filters made concrete: injection/credential blocking, PII redaction (email, phone, Aadhaar, PAN, card), poisoned-chunk flagging, secret masking | Backs "prompt safety filters"; still documented as a secondary control | `app/safety.py` |
| 9 | Minimum evaluation defined: 36 labelled questions (answerable, unanswerable, access, safety) + calibration mode | Every quality number must come from a measurement | `eval/`, `scripts/evaluate.py` |
| 10 | `/v1/metrics`: self-service rate, abstentions, blocks, latency, feedback | Lets "reduced manual query handling" be measured as a self-service rate | `app/catalog.py` |
| 11 | Power Automate: Flow B (action) is core; Flow A (SharePoint ingestion) is a stretch goal | Flow B uses only standard connectors; Flow A needs the premium HTTP connector | Spec §2, §2a; docs/05 |
| 12 | Deterministic document IDs | A free host that wipes its disk can re-ingest without duplicating vectors | `app/service.py` |
| 13 | Phase-by-phase build order with done-when checks, an explain-it check and one commit per phase | Interview on 21 October; you must be able to explain any file | docs/08 |
| 14 | Interview guide with honest claim rules and an answer on AI-assisted building | Prevents over-claiming | docs/09 |

## Not changed (deliberately)
- Python never generates free text in `/v1/search`; Copilot composes the answer.
- No public web search, no autonomous actions, no high-impact decisions.
- Catalog lifecycle state stays authoritative over Pinecone.
- No real company documents.
