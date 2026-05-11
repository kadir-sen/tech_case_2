from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    s = get_settings()
    return {
        "status": "ok",
        "llm_provider": s.llm_provider,
        "vectorstore": s.vectorstore,
    }
