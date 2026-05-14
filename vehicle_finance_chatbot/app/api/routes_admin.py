from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.llm_gateway.routing_policy import NODE_BUDGETS
from app.persistence.repositories import LLMUsageRepository
from app.rag.ingest import chunk_markdown, default_faq_path
from app.rag.retriever import FaqRetriever

router = APIRouter(prefix="/rag", tags=["rag"])

admin_router = APIRouter(prefix="/admin", tags=["admin"])
_usage_repo = LLMUsageRepository()


@router.post("/ingest")
def ingest_faq(path: str | None = None):
    target = Path(path) if path else default_faq_path()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {target}")
    docs = chunk_markdown(target)
    retriever = FaqRetriever.instance()
    new_size = retriever.ingest(docs)
    return {"ingested_chunks": len(docs), "store_size": new_size, "source": str(target)}


# --- /admin endpoints ---

@admin_router.get("/llm-usage")
def llm_usage(limit: int = 100):
    rows = _usage_repo.list_recent(limit=limit)
    return {
        "limit": limit,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "session_id": r.session_id,
                "customer_id_hash": r.customer_id_hash,
                "conversation_step": r.conversation_step,
                "node_purpose": r.node_purpose,
                "model_name": r.model_name,
                "provider": r.provider,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost_usd": r.estimated_cost_usd,
                "latency_ms": r.latency_ms,
                "litellm_call_id": r.litellm_call_id,
                "fallback_used": r.fallback_used,
                "trimmed_context_count": r.trimmed_context_count,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@admin_router.get("/llm-usage/summary")
def llm_usage_summary():
    return _usage_repo.summary()


@admin_router.get("/customer-token-usage/{customer_id}")
def customer_token_usage(customer_id: str, recent_limit: int = 20):
    """Müşteri bazlı kümülatif token kullanımı + son N çağrı metadata.

    PII içermez — customer_id istek anında hash'lenir; dönen kayıtlarda
    hash görünür. Şüpheli abuse pattern'lerini (chatbot'u kapsam dışı
    görevler için kullanma denemeleri) erken yakalamak için kullanılır.
    """
    from app.llm_gateway.usage_logger import hash_customer

    summary = _usage_repo.customer_usage_summary(hash_customer(customer_id), recent_limit=recent_limit)
    settings = get_settings()
    summary["limits"] = {
        "hourly": settings.max_tokens_per_customer_hourly,
        "daily": settings.max_tokens_per_customer_daily,
    }
    summary["status"] = {
        "over_hourly": summary.get("tokens_last_1h", 0) >= settings.max_tokens_per_customer_hourly
        if settings.max_tokens_per_customer_hourly > 0 else False,
        "over_daily": summary.get("tokens_last_24h", 0) >= settings.max_tokens_per_customer_daily
        if settings.max_tokens_per_customer_daily > 0 else False,
    }
    return summary


@admin_router.get("/llm-budget/status")
def llm_budget_status():
    settings = get_settings()
    return {
        "gateway_enabled": settings.llm_gateway_enabled,
        "litellm_base_url": settings.litellm_base_url,
        "enable_cloud_fallback": settings.enable_cloud_fallback,
        "policies": {
            name: {
                "model_alias": p.model_alias,
                "max_input_tokens": p.max_input_tokens,
                "max_output_tokens": p.max_output_tokens,
                "max_context_chunks": p.max_context_chunks,
                "temperature": p.temperature,
                "fallback_alias": p.fallback_alias,
            }
            for name, p in NODE_BUDGETS.items()
        },
    }
