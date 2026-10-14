"""
Vector stores behind one interface:

    upsert(records)                      records = [{"id", "values", "metadata"}]
    query(vector, top_k, filter) -> [{"id", "score", "metadata"}]
    delete(ids)

PineconeStore is the real one. MemoryStore mimics the same behaviour (including
the metadata filter syntax we use) so you can run and test without an account.

Security note: the *server* builds the filter (tenant namespace + allowed groups +
ACTIVE lifecycle). Callers never send filters.
"""
import json
import math
import threading
from pathlib import Path


def _match(metadata: dict, flt: dict) -> bool:
    """Tiny subset of Pinecone's filter language: $eq, $in, $ne, $and."""
    if not flt:
        return True
    for key, cond in flt.items():
        if key == "$and":
            if not all(_match(metadata, sub) for sub in cond):
                return False
            continue
        value = metadata.get(key)
        if not isinstance(cond, dict):
            cond = {"$eq": cond}
        for op, target in cond.items():
            values = value if isinstance(value, list) else [value]
            if op == "$eq" and target not in values:
                return False
            if op == "$ne" and target in values:
                return False
            if op == "$in" and not any(v in target for v in values):
                return False
    return True


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.records = {}
        if path.exists():
            self.records = json.loads(path.read_text())

    def _save(self):
        self.path.write_text(json.dumps(self.records))

    def upsert(self, records):
        with self.lock:
            for r in records:
                self.records[r["id"]] = {"values": r["values"], "metadata": r["metadata"]}
            self._save()

    def query(self, vector, top_k, flt):
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        with self.lock:
            hits = [
                {"id": rid, "score": cosine(vector, r["values"]), "metadata": r["metadata"]}
                for rid, r in self.records.items()
                if _match(r["metadata"], flt)
            ]
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    def delete(self, ids):
        with self.lock:
            for i in ids:
                self.records.pop(i, None)
            self._save()

    def healthy(self) -> bool:
        return True


class PineconeStore:
    def __init__(self, settings, dimension: int):
        from pinecone import Pinecone, ServerlessSpec

        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.namespace = settings.pinecone_namespace
        name = settings.pinecone_index
        # Create the index once, explicitly. Never delete/recreate at import time.
        if not self.pc.has_index(name):
            self.pc.create_index(
                name=name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
            )
        desc = self.pc.describe_index(name)
        existing_dim = desc["dimension"] if isinstance(desc, dict) else desc.dimension
        if int(existing_dim) != int(dimension):
            raise RuntimeError(
                f"Index '{name}' has dimension {existing_dim} but the embedding model "
                f"produces {dimension}. Use a new PINECONE_INDEX name."
            )
        self.index = self.pc.Index(name)

    def upsert(self, records):
        for start in range(0, len(records), 100):
            self.index.upsert(vectors=records[start : start + 100], namespace=self.namespace)

    def query(self, vector, top_k, flt):
        res = self.index.query(
            vector=vector,
            top_k=top_k,
            filter=flt,
            include_metadata=True,
            namespace=self.namespace,
        )
        matches = res["matches"] if isinstance(res, dict) else res.matches
        out = []
        for m in matches:
            get = m.get if isinstance(m, dict) else lambda k, _m=m: getattr(_m, k)
            out.append({"id": get("id"), "score": float(get("score")), "metadata": dict(get("metadata") or {})})
        return out

    def delete(self, ids):
        for start in range(0, len(ids), 1000):
            self.index.delete(ids=ids[start : start + 1000], namespace=self.namespace)

    def healthy(self) -> bool:
        try:
            self.index.describe_index_stats()
            return True
        except Exception:
            return False


def build_store(settings, dimension: int):
    if settings.vector_store == "memory":
        return MemoryStore(settings.data_dir / "memory_index.json")
    if settings.vector_store == "pinecone":
        if not settings.pinecone_api_key:
            raise RuntimeError("VECTOR_STORE=pinecone needs PINECONE_API_KEY")
        return PineconeStore(settings, dimension)
    raise ValueError(f"Unknown VECTOR_STORE '{settings.vector_store}'")
