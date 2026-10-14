"""
API tests through FastAPI's TestClient (needs: pip install -r requirements.txt).
    python -m pytest -q
"""
import base64
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["VECTOR_STORE"] = "memory"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["INGEST_SAMPLES_ON_STARTUP"] = "true"
os.environ["MIN_SCORE"] = "-1"  # offline hash embedder needs its own threshold, not the Pinecone 0.80 from .env
os.environ["API_KEYS_JSON"] = ""  # force demo keys: an existing (empty) var is not overridden by .env

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

EMP = {"X-API-Key": "dev-employee-key"}
HR = {"X-API-Key": "dev-hr-key"}
ADMIN = {"X-API-Key": "dev-admin-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # startup ingests sample_docs in a background thread
        for _ in range(100):  # wait up to ~10 s for the 9 sample documents
            if len(c.get("/v1/documents", headers=ADMIN).json()) >= 9:
                break
            time.sleep(0.1)
        yield c


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200


def test_requires_api_key(client):
    assert client.post("/v1/search", json={"query": "leave"}).status_code == 401
    assert client.post("/v1/search", json={"query": "leave"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_body_cannot_carry_identity(client):
    r = client.post("/v1/search", json={"query": "leave", "user_id": "admin", "groups": ["hr"]}, headers=EMP)
    assert r.status_code == 422


def test_search_contract(client):
    r = client.post("/v1/search", json={"query": "How do I submit an expense claim?", "top_k": 3}, headers=EMP)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "evidence_found"
    ev = body["evidence"][0]
    assert {"title", "content", "content_location", "score"} <= set(ev)
    assert ev["title"] == "Travel and Expense Reimbursement Policy"


def test_answer_and_feedback(client):
    r = client.post("/v1/answer", json={"query": "How do I reset my password?"}, headers=EMP).json()
    assert r["status"] == "evidence_found" and "Source:" in r["answer_text"]
    fb = client.post("/v1/feedback", json={"request_id": r["request_id"], "rating": "helpful"}, headers=EMP)
    assert fb.status_code == 200
    # another user cannot rate my request
    assert client.post("/v1/feedback", json={"request_id": r["request_id"], "rating": "helpful"}, headers=HR).status_code == 404


def test_access_boundary_over_http(client):
    q = {"query": "Project Banyan merit matrix"}
    emp = client.post("/v1/search", json=q, headers=EMP).json()
    assert all("Banyan" not in e["content"] for e in emp["evidence"])
    hr = client.post("/v1/search", json=q, headers=HR).json()
    assert hr["evidence"][0]["title"].startswith("Compensation Review")


def test_admin_only_endpoints(client):
    assert client.get("/v1/documents", headers=EMP).status_code == 403
    assert client.get("/v1/documents", headers=ADMIN).status_code == 200
    assert client.get("/v1/metrics", headers=ADMIN).json()["queries_total"] >= 1


def test_power_automate_style_ingestion_and_delete(client):
    content = base64.b64encode(b"# Shuttle\n\nThe office shuttle leaves Hitech City metro every 20 minutes.").decode()
    r = client.post("/v1/ingestion-jobs", headers=ADMIN, json={
        "file_name": "shuttle.md", "content_base64": content, "source_id": "sharepoint/items/42",
        "title": "Office Shuttle Timings", "source_uri": "https://intranet.example.com/shuttle",
        "allowed_groups": ["all"], "classification": "INTERNAL"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(20):
        job = client.get(f"/v1/ingestion-jobs/{job_id}", headers=ADMIN).json()
        if job["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["state"] == "succeeded"
    s = client.post("/v1/search", json={"query": "office shuttle timings metro"}, headers=EMP).json()
    assert s["evidence"][0]["title"] == "Office Shuttle Timings"
    d = client.post("/v1/documents/delete-by-source", json={"source_id": "sharepoint/items/42"}, headers=ADMIN)
    assert d.status_code == 202
    s = client.post("/v1/search", json={"query": "office shuttle timings metro"}, headers=EMP).json()
    assert all(e["title"] != "Office Shuttle Timings" for e in s["evidence"])
