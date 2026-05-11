from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.rag.ingest import chunk_markdown, default_faq_path
from app.rag.retriever import FaqRetriever

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/ingest")
def ingest_faq(path: str | None = None):
    target = Path(path) if path else default_faq_path()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {target}")
    docs = chunk_markdown(target)
    retriever = FaqRetriever.instance()
    new_size = retriever.ingest(docs)
    return {"ingested_chunks": len(docs), "store_size": new_size, "source": str(target)}
