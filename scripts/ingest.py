"""
Load every PDF / DOCX / TXT / MD file from a folder into the index (uses your .env).

    python scripts/ingest.py                    # sample_docs/
    python scripts/ingest.py --folder my_docs   # your own synthetic documents
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.service import AssistantService, ingest_folder  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--folder", default=str(ROOT / "sample_docs"))
args = ap.parse_args()

svc = AssistantService(settings)
print(f"Store: {settings.vector_store} | embeddings: {settings.embedding_provider} ({svc.embedder.dimension} dims)")
for r in ingest_folder(svc, Path(args.folder)):
    print(f"  {r['file']:<45} {r['state']:<10} {r['error'] or ''}")
