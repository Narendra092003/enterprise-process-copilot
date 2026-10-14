"""
SQLite catalog = the system of record (Pinecone is only the search index).

Tables
  documents  - one row per source document: title, link, allowed groups,
               classification, content hash, chunk ids, lifecycle status
  jobs       - ingestion job status (queued -> processing -> succeeded/failed/skipped)
  query_log  - one row per question: intent, outcome, score, latency.
               We do NOT store the question text (privacy).
  feedback   - helpful / not helpful per request

Lifecycle rule: a document must be ACTIVE in the catalog to be served, even if
its vectors still exist in Pinecone. Delete = mark DELETED first, clean vectors after.
For a real deployment swap SQLite for PostgreSQL; the SQL here is portable.
"""
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_id TEXT UNIQUE,
    title TEXT, source_uri TEXT, file_name TEXT,
    allowed_groups TEXT, classification TEXT, action TEXT,
    content_hash TEXT, chunk_ids TEXT, flagged_chunks INTEGER DEFAULT 0,
    status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, document_id TEXT, source_id TEXT,
    state TEXT, stage TEXT, error TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS query_log (
    request_id TEXT PRIMARY KEY, ts TEXT, principal TEXT, endpoint TEXT,
    intent TEXT, status TEXT, reason TEXT, n_evidence INTEGER,
    top_score REAL, latency_ms INTEGER, pii_redacted INTEGER
);
CREATE TABLE IF NOT EXISTS feedback (
    request_id TEXT PRIMARY KEY, principal TEXT, rating TEXT, category TEXT, ts TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Catalog:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def _exec(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _rows(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ---------------- documents ----------------
    @staticmethod
    def _doc(row):
        if not row:
            return None
        row["allowed_groups"] = json.loads(row["allowed_groups"] or "[]")
        row["chunk_ids"] = json.loads(row["chunk_ids"] or "[]")
        return row

    def get_document(self, document_id):
        rows = self._rows("SELECT * FROM documents WHERE document_id=?", (document_id,))
        return self._doc(rows[0]) if rows else None

    def get_by_source(self, source_id):
        rows = self._rows("SELECT * FROM documents WHERE source_id=?", (source_id,))
        return self._doc(rows[0]) if rows else None

    def active_documents(self, ids):
        """Return {document_id: row} for ids that are ACTIVE right now."""
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._rows(
            f"SELECT * FROM documents WHERE status='ACTIVE' AND document_id IN ({marks})", tuple(ids)
        )
        return {r["document_id"]: self._doc(r) for r in rows}

    def list_documents(self):
        return [self._doc(r) for r in self._rows("SELECT * FROM documents ORDER BY updated_at DESC")]

    def save_document(self, doc: dict):
        self._exec(
            """INSERT INTO documents (document_id, source_id, title, source_uri, file_name,
                 allowed_groups, classification, action, content_hash, chunk_ids, flagged_chunks,
                 status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(document_id) DO UPDATE SET
                 title=excluded.title, source_uri=excluded.source_uri, file_name=excluded.file_name,
                 allowed_groups=excluded.allowed_groups, classification=excluded.classification,
                 action=excluded.action, content_hash=excluded.content_hash,
                 chunk_ids=excluded.chunk_ids, flagged_chunks=excluded.flagged_chunks,
                 status=excluded.status, updated_at=excluded.updated_at""",
            (
                doc["document_id"], doc["source_id"], doc["title"], doc["source_uri"],
                doc.get("file_name", ""), json.dumps(doc["allowed_groups"]),
                doc["classification"], doc.get("action", ""), doc["content_hash"],
                json.dumps(doc["chunk_ids"]), doc.get("flagged_chunks", 0), doc["status"],
                doc.get("created_at") or now(), now(),
            ),
        )

    def set_document_status(self, document_id, status):
        self._exec(
            "UPDATE documents SET status=?, updated_at=? WHERE document_id=?",
            (status, now(), document_id),
        )

    # ---------------- jobs ----------------
    def create_job(self, source_id, document_id=None):
        job_id = new_id("job")
        self._exec(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
            (job_id, document_id, source_id, "queued", "received", None, now(), now()),
        )
        return job_id

    def update_job(self, job_id, state=None, stage=None, error=None, document_id=None):
        job = self.get_job(job_id)
        self._exec(
            "UPDATE jobs SET state=?, stage=?, error=?, document_id=?, updated_at=? WHERE job_id=?",
            (
                state or job["state"], stage or job["stage"], error,
                document_id or job["document_id"], now(), job_id,
            ),
        )

    def get_job(self, job_id):
        rows = self._rows("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        return rows[0] if rows else None

    # ---------------- logs & metrics ----------------
    def log_query(self, **row):
        self._exec(
            "INSERT INTO query_log VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["request_id"], now(), row["principal"], row["endpoint"], row["intent"],
                row["status"], row.get("reason", ""), row["n_evidence"], row.get("top_score"),
                row["latency_ms"], int(row.get("pii_redacted", 0)),
            ),
        )

    def request_owner(self, request_id):
        rows = self._rows("SELECT principal FROM query_log WHERE request_id=?", (request_id,))
        return rows[0]["principal"] if rows else None

    def save_feedback(self, request_id, principal, rating, category):
        self._exec(
            "INSERT OR REPLACE INTO feedback VALUES (?,?,?,?,?)",
            (request_id, principal, rating, category, now()),
        )

    def metrics(self):
        q = self._rows(
            """SELECT COUNT(*) total,
                 SUM(status='evidence_found') answered,
                 SUM(status IN ('no_evidence','insufficient_evidence')) abstained,
                 SUM(status='blocked') blocked,
                 SUM(pii_redacted) pii_redacted,
                 AVG(latency_ms) avg_latency_ms
               FROM query_log WHERE endpoint != 'eval'"""
        )[0]
        latencies = [r["latency_ms"] for r in self._rows(
            "SELECT latency_ms FROM query_log WHERE endpoint != 'eval' ORDER BY latency_ms")]
        p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else None
        by_intent = self._rows("SELECT intent, COUNT(*) n FROM query_log WHERE endpoint != 'eval' GROUP BY intent ORDER BY n DESC")
        fb = self._rows("SELECT rating, COUNT(*) n FROM feedback GROUP BY rating")
        docs = self._rows("SELECT status, COUNT(*) n FROM documents GROUP BY status")
        total = q["total"] or 0
        helpful = next((r["n"] for r in fb if r["rating"] == "helpful"), 0)
        rated = sum(r["n"] for r in fb)
        return {
            "queries_total": total,
            "answered_with_citation": q["answered"] or 0,
            "abstained": q["abstained"] or 0,
            "blocked_by_safety_filter": q["blocked"] or 0,
            "pii_redacted": q["pii_redacted"] or 0,
            "self_service_rate": round((q["answered"] or 0) / total, 3) if total else None,
            "avg_latency_ms": round(q["avg_latency_ms"], 1) if q["avg_latency_ms"] else None,
            "p95_latency_ms": p95,
            "by_intent": {r["intent"]: r["n"] for r in by_intent},
            "feedback": {r["rating"]: r["n"] for r in fb},
            "helpful_rate": round(helpful / rated, 3) if rated else None,
            "documents": {r["status"]: r["n"] for r in docs},
            "generated_at": now(),
        }


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self.start) * 1000)
