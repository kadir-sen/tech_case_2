from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.config import get_settings
from app.rag.ingest import chunk_markdown, default_faq_path
from app.rag.vectorstore import (
    Document,
    Hit,
    HashEmbedder,
    InMemoryVectorStore,
    get_embedder,
)
from app.security.guardrails import check_retrieved_context


@dataclass
class RetrievedContext:
    query: str
    hits: list[Hit]

    def as_prompt_context(self, max_chars: int = 1200) -> str:
        # Strip prompt-injection lines from doc chunks before building prompt.
        cleaned = check_retrieved_context([h.document.text for h in self.hits])
        joined = "\n\n---\n\n".join(cleaned)
        return joined[:max_chars]

    def citations(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for h in self.hits:
            heading = h.document.metadata.get("heading", "")
            source = h.document.metadata.get("source", "")
            label = f"{source} / {heading}" if heading else source
            if label and label not in seen:
                out.append(label)
                seen.add(label)
        return out


class FaqRetriever:
    """Singleton-style retriever. Loads the FAQ doc once and serves queries."""

    _instance: "FaqRetriever | None" = None
    _lock = Lock()

    def __init__(self) -> None:
        settings = get_settings()
        embedder = get_embedder(settings.embedding_provider)
        self._store = InMemoryVectorStore(embedder=embedder)
        self._loaded = False

    @classmethod
    def instance(cls) -> "FaqRetriever":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                cls._instance._ensure_loaded()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        path = default_faq_path()
        docs = chunk_markdown(path)
        self._store.add(docs)
        self._loaded = True

    def ingest(self, documents: list[Document]) -> int:
        self._store.add(documents)
        return self._store.size

    def search(self, query: str, k: int = 3) -> RetrievedContext:
        self._ensure_loaded()
        hits = self._store.search(query, k=k)
        return RetrievedContext(query=query, hits=hits)
