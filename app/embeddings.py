"""
Embedding providers behind one small interface:

    embed_documents(texts) -> list[list[float]]
    embed_query(text)      -> list[float]
    dimension              -> int

- PineconeEmbedder: Pinecone-hosted model (default multilingual-e5-large, 1024 dims).
  No extra API key needed beyond PINECONE_API_KEY.
- LocalEmbedder: sentence-transformers on your laptop (all-MiniLM-L6-v2, 384 dims).
- HashEmbedder: dependency-free bag-of-words hashing. NOT semantic. It exists so
  tests and the offline demo run with no accounts or internet.

Rule: one index = one model = one dimension. Never mix models in one index.
"""
import hashlib
import math
import re

STOPWORDS = set(
    """a an the and or of to in on for with by from at as is are was were be been being
    do does did i me my we our you your it its this that these those can could should
    would will shall may might must how what when where which who whom why there here
    please about into than then so if not no yes any all some get got have has had""".split()
)


def _stem(word: str) -> str:
    """Very small stemmer: leaves/leave -> leav, requested/requesting -> request."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def tokenize(text: str):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


class HashEmbedder:
    name = "hash-bow-v1"

    def __init__(self, dimension: int = 512):
        self.dimension = dimension

    def _vector(self, text: str):
        vec = [0.0] * self.dimension
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feat in features:
            h = int(hashlib.md5(feat.encode()).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if (h >> 64) & 1 else -1.0
            vec[idx] += sign * (1.0 if "_" not in feat else 0.5)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


class PineconeEmbedder:
    """Uses Pinecone Inference. e5 models need input_type 'passage' vs 'query'."""

    DIMENSIONS = {"multilingual-e5-large": 1024, "llama-text-embed-v2": 1024}

    def __init__(self, api_key: str, model: str):
        from pinecone import Pinecone

        self.pc = Pinecone(api_key=api_key)
        self.name = model
        self.dimension = self.DIMENSIONS.get(model, 1024)

    @staticmethod
    def _values(item):
        try:
            return list(item["values"])
        except (TypeError, KeyError):
            return list(item.values)

    def _embed(self, texts, input_type):
        out = []
        for start in range(0, len(texts), 90):  # stay under per-request input limits
            batch = texts[start : start + 90]
            res = self.pc.inference.embed(
                model=self.name,
                inputs=batch,
                parameters={"input_type": input_type, "truncate": "END"},
            )
            out.extend(self._values(e) for e in res)
        return out

    def embed_documents(self, texts):
        return self._embed(texts, "passage")

    def embed_query(self, text):
        return self._embed([text], "query")[0]


class LocalEmbedder:
    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model)
        self.name = model
        self.dimension = self.model.get_sentence_embedding_dimension()

    def embed_documents(self, texts):
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text):
        return self.model.encode([text], normalize_embeddings=True)[0].tolist()


def build_embedder(settings):
    provider = settings.embedding_provider
    if provider == "hash":
        return HashEmbedder()
    if provider == "pinecone":
        if not settings.pinecone_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=pinecone needs PINECONE_API_KEY")
        return PineconeEmbedder(settings.pinecone_api_key, settings.pinecone_embed_model)
    if provider == "local":
        return LocalEmbedder(settings.local_embed_model)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER '{provider}'")
