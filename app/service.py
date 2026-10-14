"""
The core logic, independent of the web framework (easy to unit-test).

    ingest_document(...)  parse -> chunk -> safety scan -> embed -> upsert -> catalog
    search(...)           safety check -> embed query -> filtered vector search
                          -> catalog re-check -> threshold -> evidence
    answer(...)           search + intent detection + response template
    delete_document(...)  mark DELETED first, then remove vectors
"""
import hashlib
import re
from dataclasses import dataclass

from . import safety, templates
from .catalog import Catalog, Timer, new_id
from .chunking import chunk_pages
from .embeddings import build_embedder
from .parsing import ParseError, parse_file
from .vectorstore import build_store

VALID_CLASSIFICATIONS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL"}
GROUP_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


@dataclass
class Principal:
    """Who is calling. Built by auth.py from the API key - never from the request body."""

    name: str
    groups: list
    admin: bool = False


class AssistantService:
    def __init__(self, settings):
        self.settings = settings
        self.embedder = build_embedder(settings)
        self.store = build_store(settings, self.embedder.dimension)
        self.catalog = Catalog(settings.data_dir / "catalog.db")

    # ------------------------------------------------------------------ ingest
    def ingest_document(
        self,
        *,
        file_name: str,
        data: bytes,
        source_id: str = "",
        title: str = "",
        source_uri: str = "",
        allowed_groups=None,
        classification: str = "",
        action: str = "",
        job_id: str = "",
    ) -> dict:
        """Synchronous ingestion. Returns the final job record."""
        source_id = source_id or file_name
        job_id = job_id or self.catalog.create_job(source_id)
        try:
            if len(data) > self.settings.max_upload_mb * 1024 * 1024:
                raise ParseError(f"File larger than {self.settings.max_upload_mb} MB")
            content_hash = hashlib.sha256(data).hexdigest()
            existing = self.catalog.get_by_source(source_id)

            # Idempotency: same source + same bytes = nothing to do.
            if existing and existing["content_hash"] == content_hash and existing["status"] == "ACTIVE":
                self.catalog.update_job(job_id, "skipped", "duplicate", document_id=existing["document_id"])
                return self.catalog.get_job(job_id)

            self.catalog.update_job(job_id, "processing", "parsing")
            parsed = parse_file(file_name, data)
            fm = parsed.front_matter  # metadata embedded in sample .md files

            title = title or fm.get("title") or file_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
            source_uri = source_uri or fm.get("source_url", "")
            groups = allowed_groups or [g.strip() for g in fm.get("allowed_groups", "all").split(",")]
            groups = sorted({g.lower() for g in groups if g})
            if not groups or not all(GROUP_RE.match(g) for g in groups):
                raise ParseError("allowed_groups must be short lowercase names, e.g. ['all'] or ['hr']")
            classification = (classification or fm.get("classification") or "INTERNAL").upper()
            if classification not in VALID_CLASSIFICATIONS:
                raise ParseError(f"classification must be one of {sorted(VALID_CLASSIFICATIONS)}")
            action = action or fm.get("action", "")

            self.catalog.update_job(job_id, stage="chunking")
            chunks = chunk_pages(parsed.pages, self.settings.chunk_words, self.settings.chunk_overlap_words)
            if not chunks:
                raise ParseError("Document produced no chunks")

            # Deterministic ID from the source ID: if the catalog is wiped (e.g. a free
            # host restarts) re-ingesting overwrites the same vectors instead of duplicating.
            document_id = existing["document_id"] if existing else "doc_" + hashlib.sha1(source_id.encode()).hexdigest()[:16]
            version = content_hash[:12]
            flagged = 0
            texts, metas, ids = [], [], []
            for c in chunks:
                is_flagged = safety.scan_text(c.text)
                flagged += int(is_flagged)
                ids.append(f"{document_id}#{version}#{c.index}")
                # Embed the heading + title with the text: better retrieval for short sections.
                texts.append(f"{title}. {c.section}. {c.text}")
                metas.append(
                    {
                        "document_id": document_id,
                        "version": version,
                        "title": title,
                        "section": c.section or "",
                        "page": c.page,
                        "chunk_index": c.index,
                        "source_uri": source_uri or "",
                        "allowed_groups": groups,
                        "classification": classification,
                        "lifecycle": "ACTIVE",
                        "flagged": is_flagged,
                        "action": action or "",
                        "chunk_text": c.text[:3000],
                    }
                )

            self.catalog.update_job(job_id, stage="embedding")
            vectors = self.embedder.embed_documents(texts)

            self.catalog.update_job(job_id, stage="indexing")
            self.store.upsert(
                [{"id": i, "values": v, "metadata": m} for i, v, m in zip(ids, vectors, metas)]
            )
            # New version is live -> remove the previous version's vectors.
            if existing:
                old = [cid for cid in existing["chunk_ids"] if cid not in set(ids)]
                if old:
                    self.store.delete(old)

            self.catalog.save_document(
                {
                    "document_id": document_id,
                    "source_id": source_id,
                    "title": title,
                    "source_uri": source_uri,
                    "file_name": file_name,
                    "allowed_groups": groups,
                    "classification": classification,
                    "action": action,
                    "content_hash": content_hash,
                    "chunk_ids": ids,
                    "flagged_chunks": flagged,
                    "status": "ACTIVE",
                    "created_at": existing["created_at"] if existing else None,
                }
            )
            self.catalog.update_job(job_id, "succeeded", "done", document_id=document_id)
        except ParseError as exc:
            self.catalog.update_job(job_id, "failed", "validation", error=str(exc))
        except Exception as exc:  # provider/network errors: safe message, details in server log
            print(f"[ingest] job {job_id} failed: {exc!r}")
            self.catalog.update_job(job_id, "failed", "processing", error="INTERNAL_ERROR")
        return self.catalog.get_job(job_id)

    # ------------------------------------------------------------------ delete
    def delete_document(self, document_id: str) -> bool:
        doc = self.catalog.get_document(document_id)
        if not doc or doc["status"] == "DELETED":
            return False
        self.catalog.set_document_status(document_id, "DELETED")  # stop serving first
        self.store.delete(doc["chunk_ids"])  # then clean up vectors
        return True

    # ------------------------------------------------------------------ search
    def _filter(self, principal: Principal) -> dict:
        # Built on the server only. Groups come from the API key, not the request.
        return {
            "$and": [
                {"allowed_groups": {"$in": principal.groups}},
                {"lifecycle": {"$eq": "ACTIVE"}},
                {"flagged": {"$eq": False}},
            ]
        }

    def search(self, query: str, principal: Principal, top_k: int = 5, endpoint: str = "search") -> dict:
        request_id = new_id("req")
        top_k = max(1, min(int(top_k or 5), self.settings.max_top_k))
        with Timer() as t:
            check = safety.check_query(query, self.settings.max_query_chars)
            if not check.allowed:
                result = {"status": "blocked", "evidence": [], "abstention_reason": check.reason, "intent": "blocked"}
            else:
                result = self._retrieve(check.clean_query, principal, top_k)
                result["intent"] = templates.detect_intent(check.clean_query)
        result["request_id"] = request_id
        result["pii_redacted"] = check.pii_found
        self.catalog.log_query(
            request_id=request_id,
            principal=principal.name,
            endpoint=endpoint,
            intent=result["intent"],
            status=result["status"],
            reason=result.get("abstention_reason") or "",
            n_evidence=len(result["evidence"]),
            top_score=result["evidence"][0]["score"] if result["evidence"] else None,
            latency_ms=t.ms,
            pii_redacted=bool(check.pii_found),
        )
        return result

    def _retrieve(self, query: str, principal: Principal, top_k: int) -> dict:
        vector = self.embedder.embed_query(query)
        hits = self.store.query(vector, self.settings.candidate_k, self._filter(principal))

        # Defence in depth: re-check every hit against the catalog (current status,
        # current version, groups) before anything leaves the server.
        active = self.catalog.active_documents(list({h["metadata"]["document_id"] for h in hits}))
        allowed = []
        for h in hits:
            m = h["metadata"]
            doc = active.get(m["document_id"])
            if not doc or m.get("version") != doc["content_hash"][:12]:
                continue
            if not set(doc["allowed_groups"]) & set(principal.groups):
                continue
            if safety.scan_text(m.get("chunk_text", "")):
                continue
            allowed.append(h)

        if not allowed:
            return {"status": "no_evidence", "evidence": [], "abstention_reason": "NO_APPROVED_SOURCE"}

        min_score = self.settings.effective_min_score
        if allowed[0]["score"] < min_score:
            return {"status": "insufficient_evidence", "evidence": [], "abstention_reason": "LOW_CONFIDENCE"}

        evidence, seen = [], set()
        for h in allowed:
            m = h["metadata"]
            key = (m["document_id"], m.get("section"))
            if h["score"] < min_score or key in seen:  # drop weak + duplicate sections
                continue
            seen.add(key)
            evidence.append(
                {
                    "evidence_id": h["id"],
                    "title": m["title"],
                    "content": safety.redact_secrets(m.get("chunk_text", "")),
                    "content_location": m.get("source_uri", ""),
                    "document_id": m["document_id"],
                    "section": m.get("section", ""),
                    "page": int(m.get("page", 1)),
                    "score": round(h["score"], 4),
                    "action": m.get("action", ""),
                }
            )
            if len(evidence) >= top_k:
                break
        return {"status": "evidence_found", "evidence": evidence, "abstention_reason": None}

    # ------------------------------------------------------------------ answer
    def answer(self, query: str, principal: Principal, top_k: int = 3) -> dict:
        res = self.search(query, principal, max(top_k, 4), endpoint="answer")
        route = self.settings.support_route
        suggested_action = ""
        if res["status"] == "blocked":
            text = templates.render_blocked(res["abstention_reason"])
        elif res["status"] != "evidence_found":
            text = templates.render_no_evidence(res["abstention_reason"], route)
        else:
            text = templates.render_answer(res["intent"], res["evidence"], route)
            suggested_action = res["evidence"][0].get("action", "")
            if suggested_action and res["intent"] == "how_to":
                text += "\n\n" + templates.action_prompt(suggested_action)
            else:
                suggested_action = ""
        return {
            "request_id": res["request_id"],
            "status": res["status"],
            "intent": res["intent"],
            "answer_text": text,
            "citations": [
                {"title": e["title"], "url": e["content_location"], "section": e["section"], "page": e["page"]}
                for e in res["evidence"]
            ],
            "suggested_action": suggested_action,
            "abstention_reason": res["abstention_reason"],
        }


def ingest_folder(svc: AssistantService, folder) -> list:
    """Ingest every supported file in a folder (used for sample_docs and scripts)."""
    results = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}:
            job = svc.ingest_document(file_name=path.name, data=path.read_bytes(), source_id=f"sample/{path.name}")
            results.append({"file": path.name, "state": job["state"], "error": job["error"]})
    return results
