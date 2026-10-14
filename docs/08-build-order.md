# 08 — Build Order and Day Plan

Section 12 of [`../PROJECT_SPECIFICATION.md`](../PROJECT_SPECIFICATION.md) is authoritative if this summary differs.

This phase plan is historical. For the implemented Copilot Studio and Power Automate paths, see [04](04-copilot-studio.md) and [05](05-power-automate.md); measured completion evidence is in [EVALUATION.md](EVALUATION.md).

## How to use the reference implementation

Keep this extracted package as the **reference copy** (`copilot-assistant-reference/`) and build in a fresh folder (`copilot-assistant/`). For each phase, read the reference file, write your version (with your AI assistant if you like), run the check, and commit. Copy only what you understand. If a phase runs out of time, copying the reference file is acceptable, but you must still pass the explain-it check.

## Phases

| # | Build | Reference files | Done when |
|---:|---|---|---|
| 1 | Scaffold: folders, `requirements.txt`, `.gitignore`, `.env.example`, README stub, venv | root files | `pip install -r requirements.txt` works; `.env` ignored by git |
| 2 | Settings | `app/config.py` | `python -c "from app.config import settings; print(settings.vector_store)"` prints `memory` |
| 3 | Parsing: TXT/MD (+ front matter), PDF pages, DOCX | `app/parsing.py` | Each sample doc parses; a `.exe` or empty file gives a clear error |
| 4 | Section-aware chunking with overlap | `app/chunking.py` | Leave policy chunks have section names; long text splits with overlap |
| 5 | Embeddings (hash first) + memory vector store with filter | `app/embeddings.py`, `app/vectorstore.py` | Upsert 3 vectors, query with an `allowed_groups` filter, get the right one |
| 6 | Catalog (SQLite) | `app/catalog.py` | Save a document, create and update a job, read them back |
| 7 | Ingestion service: idempotency, versions, delete lifecycle | `app/service.py` (`ingest_document`, `delete_document`, `ingest_folder`) | `scripts/ingest.py` → 9 × succeeded; second run → skipped |
| 8 | Safety filters | `app/safety.py` | Injection blocked, "password reset process" allowed, PII redacted |
| 9 | Retrieval: server filter, catalog re-check, threshold, dedupe | `app/service.py` (`_filter`, `search`, `_retrieve`) | Employee can't see the HR doc; HR can; cafeteria question abstains |
| 10 | Response templates + `answer()` | `app/templates.py`, `answer()` | How-to question shows numbered steps + citation + action offer |
| 11 | FastAPI app, auth, rate limit, all endpoints | `app/main.py`, `app/auth.py` | `/docs` works; 401 without key; 422 when the body has `user_id` |
| 12 | Test console | `app/static/index.html` | Ask questions as Employee and HR from the browser |
| 13 | Tests + evaluation | `tests/`, `scripts/evaluate.py`, `eval/questions.json` | `pytest` green; evaluation report printed |
| 14 | **Pinecone**: switch `.env`, ingest, calibrate `MIN_SCORE`, re-evaluate | docs/03 | Records visible in the Pinecone console; numbers saved in `docs/EVALUATION.md` |
| 15 | Public URL with real keys (ngrok) | docs/06 | `https://.../health/ready` works from your phone |
| 16 | Copilot Studio agent: Option A topic, then Option B knowledge topic | docs/04, `copilot/` | Test panel gives a cited answer from your API |
| 17 | Power Automate Flow B + `Raise access request` topic with confirmation | docs/05, `powerautomate/` | Yes → one list row + approval email; No → nothing |
| 18 | Polish: screenshots, backup video, README, GitHub | docs/07, docs/09 | Repo pushed (no secrets); demo rehearsed twice |
| S | Stretch: Flow A/A2 SharePoint ingestion, Render, local embeddings | docs/05, docs/06 | Uploading to SharePoint makes a doc searchable |

**Cut line:** phases 1–14 plus 16 (Option A) must be done. They give a working, measured and demoable system.

## Day plan — if this is your only project

| Day | Phases | Goal |
|---|---|---|
| Wed 14 Oct | 1–5 + **start Copilot Studio sign-up and Pinecone/ngrok accounts** | Documents become searchable chunks |
| Thu 15 Oct | 6–10 | Ingest, safety and retrieval work in Python |
| Fri 16 Oct | 11–14 | API live; Pinecone numbers measured |
| Sat 17 Oct | 15–16 | Copilot Studio answers from your API |
| Sun 18 Oct | 17 | Confirmed action with approval works |
| Mon 19 Oct | 18 (+ stretch if time) | Demo-ready, video recorded |
| Tue 20 Oct | — | Interview prep with docs/09; read your own code |

## Day plan — if you are also building IP Lens this week

IP Lens's plan uses Wed–Sun at 6–8 hours a day, so don't rebuild this project phase by phase. Run the **reference implementation** and invest in understanding plus the Microsoft integration:

| When | Do | Time |
|---|---|---|
| Wed 14 evening | Start Copilot Studio sign-up (account approval can take time); create Pinecone + ngrok accounts; run Quick start offline | 45 min |
| Thu 15 – Sun 18 evenings | 30 min a day: read one module per day (`service.py`, `safety.py` + `templates.py`, `chunking.py` + `parsing.py`, `main.py` + `auth.py`) and pass the explain-it check | 4 × 30 min |
| Mon 19 (IP Lens buffer day) | Phase 14 (Pinecone + calibration + numbers), 15 (ngrok), 16 Option A | 4 h |
| Tue 20 | Phase 17 (Flow B) if the tenant is ready, rehearse both demos, record backups | 4 h |
| Wed 21 | Interview | — |

If Copilot Studio access isn't ready by Monday, demo with the test console and Swagger, and walk through the Copilot YAML and flow design. Say plainly what you did and didn't wire up.

## Working agreement for each phase (same as IP Lens)

1. Ask the AI coding assistant to inspect the workspace, state the phase goal, and list the files it will touch.
2. Keep changes limited to that phase.
3. Run the phase's "done when" check yourself.
4. **Explain-it check:** before moving on, explain out loud in two or three sentences what each new file does and why. If you can't, go through it until you can.
5. Commit, for example `Phase 9: server-side access filter and abstention`.

**Never cut:** the server-side access filter + catalog re-check, the abstention threshold, the safety filters, and the measured evaluation. They are what make the project credible.
