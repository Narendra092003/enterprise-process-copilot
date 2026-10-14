"""
FastAPI app: the REST layer that Copilot Studio and Power Automate call.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs  (Swagger UI - also the OpenAPI file you can
      import into a Power Platform custom connector: /openapi.json)
"""
import base64
import binascii
import threading
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_admin, require_user
from .config import PROJECT_ROOT, settings
from .service import AssistantService, Principal, ingest_folder

service: Optional[AssistantService] = None


def get_service() -> AssistantService:
    return service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global service
    service = AssistantService(settings)
    if settings.using_default_keys:
        print("[warn] Using built-in DEMO API keys. Set API_KEYS_JSON before exposing this API publicly.")
    if settings.ingest_samples_on_startup:
        # Run in a background thread so the server opens its port immediately.
        # (Hosts like Render fail the deploy if the port isn't open within a time limit.)
        def _load_samples():
            try:
                for r in ingest_folder(service, PROJECT_ROOT / "sample_docs"):
                    print(f"[startup] {r['file']}: {r['state']}", flush=True)
            except Exception as exc:  # never crash the server because of sample loading
                print(f"[startup] sample ingestion failed: {exc!r}", flush=True)

        threading.Thread(target=_load_samples, daemon=True).start()
    yield


app = FastAPI(
    title="Enterprise Process Copilot - Retrieval API",
    version="1.0.0",
    description="Grounded search over internal process documents for Copilot Studio and Power Automate.",
    lifespan=lifespan,
)
if settings.allowed_origins:  # never '*' - list your own front-end origins only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )


# ----------------------------------------------------------------- schemas
class Strict(BaseModel):
    # extra="forbid": a caller cannot sneak in user_id / groups / filters.
    model_config = ConfigDict(extra="forbid")


class SearchRequest(Strict):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    conversation_id: Optional[str] = Field(None, max_length=200)


class Evidence(BaseModel):
    evidence_id: str
    title: str
    content: str
    content_location: str
    document_id: str
    section: str
    page: int
    score: float
    action: str = ""


class SearchResponse(BaseModel):
    request_id: str
    status: Literal["evidence_found", "no_evidence", "insufficient_evidence", "blocked"]
    intent: str
    evidence: List[Evidence]
    abstention_reason: Optional[str]


class AnswerRequest(Strict):
    query: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(None, max_length=200)


class Citation(BaseModel):
    title: str
    url: str
    section: str
    page: int


class AnswerResponse(BaseModel):
    request_id: str
    status: str
    intent: str
    answer_text: str
    citations: List[Citation]
    suggested_action: str
    abstention_reason: Optional[str]


class FeedbackRequest(Strict):
    request_id: str = Field(..., max_length=64)
    rating: Literal["helpful", "not_helpful"]
    category: Literal["missing_source", "incorrect", "stale", "other", "none"] = "none"


class IngestRequest(Strict):
    """JSON ingestion - this is what the Power Automate flow sends."""

    file_name: str = Field(..., max_length=255)
    content_base64: str
    source_id: str = Field(..., max_length=500, description="Stable ID from the source, e.g. SharePoint item ID")
    title: str = Field("", max_length=300)
    source_uri: str = Field("", max_length=1000)
    allowed_groups: List[str] = Field(default_factory=lambda: ["all"])
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"] = "INTERNAL"
    action: str = Field("", max_length=64)


class DeleteBySourceRequest(Strict):
    source_id: str = Field(..., max_length=500)


# ----------------------------------------------------------------- routes
@app.get("/", include_in_schema=False)
def home():
    return FileResponse(PROJECT_ROOT / "app" / "static" / "index.html")


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(svc: AssistantService = Depends(get_service)):
    ok = svc is not None and svc.store.healthy()
    return JSONResponse({"status": "ready" if ok else "not_ready"}, status_code=200 if ok else 503)


@app.get("/v1/me", tags=["employee"])
def me(p: Principal = Depends(require_user)):
    return {"principal": p.name, "groups": p.groups, "admin": p.admin}


@app.post("/v1/search", response_model=SearchResponse, tags=["employee"])
def search(body: SearchRequest, p: Principal = Depends(require_user), svc: AssistantService = Depends(get_service)):
    """Evidence only (no generated text). Use with Copilot Studio's custom knowledge topic."""
    res = svc.search(body.query, p, body.top_k)
    return {k: res[k] for k in ("request_id", "status", "intent", "evidence", "abstention_reason")}


@app.post("/v1/answer", response_model=AnswerResponse, tags=["employee"])
def answer(body: AnswerRequest, p: Principal = Depends(require_user), svc: AssistantService = Depends(get_service)):
    """Ready-to-show answer built from a response template + citations."""
    return svc.answer(body.query, p)


@app.post("/v1/feedback", tags=["employee"])
def feedback(body: FeedbackRequest, p: Principal = Depends(require_user), svc: AssistantService = Depends(get_service)):
    if svc.catalog.request_owner(body.request_id) != p.name:
        raise HTTPException(404, "Unknown request_id")
    svc.catalog.save_feedback(body.request_id, p.name, body.rating, body.category)
    return {"status": "recorded"}


@app.post("/v1/ingestion-jobs", status_code=202, tags=["admin"])
def create_ingestion_job(
    body: IngestRequest,
    background: BackgroundTasks,
    p: Principal = Depends(require_admin),
    svc: AssistantService = Depends(get_service),
):
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "content_base64 is not valid base64") from None
    job_id = svc.catalog.create_job(body.source_id)
    background.add_task(
        svc.ingest_document,
        file_name=body.file_name,
        data=data,
        source_id=body.source_id,
        title=body.title,
        source_uri=body.source_uri,
        allowed_groups=body.allowed_groups,
        classification=body.classification,
        action=body.action,
        job_id=job_id,
    )
    return {"job_id": job_id, "state": "queued", "status_url": f"/v1/ingestion-jobs/{job_id}"}


@app.post("/v1/documents/upload", status_code=202, tags=["admin"])
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    source_uri: str = Form(""),
    allowed_groups: str = Form("all", description="Comma separated, e.g. all or hr"),
    classification: str = Form("INTERNAL"),
    action: str = Form(""),
    p: Principal = Depends(require_admin),
    svc: AssistantService = Depends(get_service),
):
    data = await file.read()
    source_id = f"upload/{file.filename}"
    job_id = svc.catalog.create_job(source_id)
    background.add_task(
        svc.ingest_document,
        file_name=file.filename,
        data=data,
        source_id=source_id,
        title=title,
        source_uri=source_uri,
        allowed_groups=[g.strip() for g in allowed_groups.split(",") if g.strip()],
        classification=classification,
        action=action,
        job_id=job_id,
    )
    return {"job_id": job_id, "state": "queued", "status_url": f"/v1/ingestion-jobs/{job_id}"}


@app.get("/v1/ingestion-jobs/{job_id}", tags=["admin"])
def get_job(job_id: str, p: Principal = Depends(require_admin), svc: AssistantService = Depends(get_service)):
    job = svc.catalog.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/v1/documents", tags=["admin"])
def list_documents(p: Principal = Depends(require_admin), svc: AssistantService = Depends(get_service)):
    return [
        {k: d[k] for k in ("document_id", "source_id", "title", "allowed_groups", "classification",
                           "status", "flagged_chunks", "updated_at")} | {"chunks": len(d["chunk_ids"])}
        for d in svc.catalog.list_documents()
    ]


@app.delete("/v1/documents/{document_id}", status_code=202, tags=["admin"])
def delete_document(document_id: str, p: Principal = Depends(require_admin), svc: AssistantService = Depends(get_service)):
    if not svc.delete_document(document_id):
        raise HTTPException(404, "Document not found")
    return {"document_id": document_id, "status": "DELETED"}


@app.post("/v1/documents/delete-by-source", status_code=202, tags=["admin"])
def delete_by_source(body: DeleteBySourceRequest, p: Principal = Depends(require_admin), svc: AssistantService = Depends(get_service)):
    """For the Power Automate 'file deleted' trigger, which only knows the source item ID."""
    doc = svc.catalog.get_by_source(body.source_id)
    if not doc or not svc.delete_document(doc["document_id"]):
        raise HTTPException(404, "Document not found")
    return {"document_id": doc["document_id"], "status": "DELETED"}


@app.get("/v1/metrics", tags=["admin"])
def metrics(p: Principal = Depends(require_admin), svc: AssistantService = Depends(get_service)):
    """Numbers for your dashboard / resume: self-service rate, abstentions, blocked, latency."""
    return svc.catalog.metrics()
