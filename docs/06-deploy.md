# 06 — Public URL / Deployment

Copilot Studio and Power Automate run in Microsoft's cloud and need an **HTTPS URL** they can reach.

## Before exposing anything: set real keys

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # run twice, one key each
```

In `.env`:

```env
API_KEYS_JSON={"PASTE-KEY-1": {"principal": "copilot-studio", "groups": ["all"], "admin": false}, "PASTE-KEY-2": {"principal": "power-automate-ingest", "groups": ["all","hr","it"], "admin": true}}
```

Once `API_KEYS_JSON` is set, the demo keys (`dev-...`) stop working. Then:
- Key 1 → Copilot Studio HTTP nodes (can only see `all` documents)
- Key 2 → Power Automate Flow A (admin: ingest and delete)
- To keep the HR demo, add a third non-admin key with groups `["all","hr"]`

The test console's dropdown uses the `dev-...` keys, so it only works on your laptop with the default keys.

## Option 1 — ngrok (fastest, best for the demo)

1. Sign up at https://ngrok.com, install it, and run `ngrok config add-authtoken <token>` once.
2. Start the API: `uvicorn app.main:app --port 8000`
3. In a second terminal: `ngrok http 8000`
4. Copy the `https://....ngrok-free.app` URL into Copilot Studio and the flows.

Notes: the free URL changes every time you restart ngrok, unless you claim the free static domain in the ngrok dashboard (recommended: claim it and run `ngrok http --url=<your-domain> 8000`). If an HTTP call returns an HTML warning page instead of JSON, add the header `ngrok-skip-browser-warning: true` to that HTTP node or action.

## Option 2 — Render (always-on URL, free tier)

1. Push the project to GitHub. `.gitignore` already excludes `.env` and `data/`. Check that no key is committed.
2. https://render.com → **New** → **Blueprint** → select the repo (it reads `render.yaml`).
3. In the service's **Environment** tab set `PINECONE_API_KEY`, `API_KEYS_JSON` and `MIN_SCORE`.
4. Deploy, then open `https://<name>.onrender.com/health/live`.

Free Render services **sleep after inactivity**, and the first request can take about a minute, which is longer than Copilot's 30-second HTTP timeout. **Open `/health/live` in a browser 2 minutes before your demo.** The disk resets on restart, so `INGEST_SAMPLES_ON_STARTUP=true` reloads the sample documents. Vectors in Pinecone are overwritten, not duplicated, because document IDs are deterministic.

## Option 3 — Docker (anywhere)

```bash
docker build -t ops-copilot-api .
docker run -p 8000:8000 --env-file .env ops-copilot-api
```

Azure Container Apps or App Service is the production target in the spec: Key Vault for secrets, managed identity, Application Insights for logs.

## Pre-demo checklist

- [ ] `GET /health/ready` returns `ready`
- [ ] `GET /v1/documents` (admin key) lists the documents as ACTIVE
- [ ] Copilot test panel answers one question end to end
- [ ] `.env` is not in GitHub (search your repo for `pcsk_`)
