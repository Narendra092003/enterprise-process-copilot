# 02 — Run Locally (Offline Mode)

Offline mode needs no accounts. It uses an in-memory vector store saved to `data/memory_index.json` and a simple word-hashing "embedding". It is not semantic, but it lets you learn the whole pipeline first.

## 1. Install

Requires Python 3.10 or newer (3.12 recommended).

```bash
cd copilot-assistant
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
```

## 2. Load the sample documents

```bash
python scripts/ingest.py
```

You should see 9 files with `succeeded`. The vendor onboarding document contains a planted "ignore all previous instructions" paragraph. That chunk is flagged and never returned.

## 3. Start the API

```bash
uvicorn app.main:app --reload --port 8000
```

- http://localhost:8000/ — test console. Switch between the "Employee" and "HR partner" identities to see access control.
- http://localhost:8000/docs — Swagger. Click **Authorize** and paste `dev-employee-key` (or `dev-admin-key` for admin endpoints).

## 4. Try it from the command line

```bash
curl -s -X POST http://localhost:8000/v1/search -H "Content-Type: application/json" -H "X-API-Key: dev-employee-key" -d "{\"query\": \"How do I submit an expense claim?\", \"top_k\": 3}"

curl -s -X POST http://localhost:8000/v1/answer -H "Content-Type: application/json" -H "X-API-Key: dev-employee-key" -d "{\"query\": \"How many casual leaves do I get?\"}"

curl -s http://localhost:8000/v1/metrics -H "X-API-Key: dev-admin-key"
```

Upload your own file:

```bash
curl -s -X POST http://localhost:8000/v1/documents/upload -H "X-API-Key: dev-admin-key" -F "file=@my-policy.pdf" -F "title=My Policy" -F "allowed_groups=all"
```

## 5. Run the tests and the evaluation

```bash
python -m pytest -q                 # 27 automated tests
python scripts/evaluate.py -v       # retrieval + safety report
```

The measured offline hash baseline hit@1 is 26/27. The Pinecone e5 results to quote are recorded in [docs/EVALUATION.md](EVALUATION.md).

## Reading order for the code (about 1 hour)

1. `app/service.py` — the whole pipeline in one file
2. `app/safety.py` and `app/templates.py`
3. `app/chunking.py`, `app/parsing.py`
4. `app/vectorstore.py` (compare `MemoryStore` and `PineconeStore`)
5. `app/main.py` (endpoints) and `app/auth.py`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: app` | Run commands from the `copilot-assistant` folder |
| 401 Missing or invalid API key | Add header `X-API-Key: dev-employee-key` |
| 422 on /v1/search | The body must contain only `query`, `top_k`, `conversation_id` |
| Changed `.env` but nothing changed | Restart uvicorn |
| Want a clean start | Stop the server and delete the `data/` folder |
