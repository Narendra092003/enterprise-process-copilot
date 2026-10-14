import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_API_KEYS = {
    "dev-employee-key": {"principal": "demo-employee", "groups": ["all"], "admin": False},
    "dev-hr-key": {"principal": "demo-hr-partner", "groups": ["all", "hr"], "admin": False},
    "dev-admin-key": {"principal": "demo-admin", "groups": ["all", "hr", "it"], "admin": True},
}


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # which store and embedding model to use
    vector_store: str = os.getenv("VECTOR_STORE", "memory")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "hash")

    # Pinecone
    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", "")
    pinecone_index: str = os.getenv("PINECONE_INDEX", "ops-assistant")
    pinecone_namespace: str = os.getenv("PINECONE_NAMESPACE", "tenant-demo")
    pinecone_cloud: str = os.getenv("PINECONE_CLOUD", "aws")
    pinecone_region: str = os.getenv("PINECONE_REGION", "us-east-1")
    pinecone_embed_model: str = os.getenv("PINECONE_EMBED_MODEL", "multilingual-e5-large")
    local_embed_model: str = os.getenv("LOCAL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    # retrieval
    chunk_words: int = int(os.getenv("CHUNK_WORDS", "180"))
    chunk_overlap_words: int = int(os.getenv("CHUNK_OVERLAP_WORDS", "30"))
    candidate_k: int = int(os.getenv("CANDIDATE_K", "20"))
    max_top_k: int = int(os.getenv("MAX_TOP_K", "8"))
    min_score: float = float(os.getenv("MIN_SCORE", "-1"))

    # safety and limits
    max_query_chars: int = int(os.getenv("MAX_QUERY_CHARS", "500"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    support_route: str = os.getenv("SUPPORT_ROUTE", "the IT/Operations Service Desk (servicedesk@example.com)")

    # storage
    data_dir: Path = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
    ingest_samples_on_startup: bool = _bool("INGEST_SAMPLES_ON_STARTUP", False)
    allowed_origins: list = field(
        default_factory=lambda: [o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o]
    )
    api_keys: dict = field(default_factory=dict)

    def __post_init__(self):
        raw = os.getenv("API_KEYS_JSON", "").strip()
        self.api_keys = json.loads(raw) if raw else dict(DEFAULT_API_KEYS)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def effective_min_score(self) -> float:
        if self.min_score >= 0:
            return self.min_score
        return {"hash": 0.18, "pinecone": 0.78, "local": 0.35}.get(self.embedding_provider, 0.3)

    @property
    def using_default_keys(self) -> bool:
        return not os.getenv("API_KEYS_JSON", "").strip()


settings = Settings()