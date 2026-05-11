from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Document:
    id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic, dependency-free embedder for tests and CI.

    Uses a hashed bag-of-character-trigrams projection. It is not semantically
    rich, but it is stable across runs and works without downloading models —
    which is required so tests can run offline.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        norm_text = " ".join(text.lower().split())
        if not norm_text:
            return v
        # Character trigrams
        padded = f"  {norm_text}  "
        for i in range(len(padded) - 2):
            tri = padded[i : i + 3]
            h = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            v[idx] += sign
        # Word unigrams
        for word in norm_text.split():
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            v[idx] += 1.0
        # L2-normalize
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0:
            v = [x / norm for x in v]
        return v

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_embedder(provider: str = "hash"):
    if provider == "sentence-transformers":
        try:  # Lazy import — heavy.
            from sentence_transformers import SentenceTransformer  # type: ignore

            from app.config import get_settings

            model_name = get_settings().embedding_model
            model = SentenceTransformer(model_name)

            class _STEmbedder:
                def embed(self, texts: list[str]) -> list[list[float]]:
                    return [list(map(float, v)) for v in model.encode(texts, normalize_embeddings=True)]

            return _STEmbedder()
        except Exception:
            # Fall back silently so MVP keeps running.
            return HashEmbedder()
    return HashEmbedder()


@dataclass
class Hit:
    document: Document
    score: float


class InMemoryVectorStore:
    """Cosine-similarity vector store. Default implementation for MVP/tests.

    Qdrant integration is wired in app/rag/retriever.py when configured.
    """

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._docs: list[Document] = []
        self._vecs: list[list[float]] = []

    def add(self, documents: list[Document]) -> None:
        vecs = self.embedder.embed([d.text for d in documents])
        self._docs.extend(documents)
        self._vecs.extend(vecs)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        if not self._docs:
            return []
        q = self.embedder.embed([query])[0]
        scored: list[Hit] = []
        for doc, vec in zip(self._docs, self._vecs):
            score = sum(a * b for a, b in zip(q, vec))
            scored.append(Hit(document=doc, score=score))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    @property
    def size(self) -> int:
        return len(self._docs)
