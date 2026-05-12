"""Post-call usage logging.

We log token counts, latency, and estimated cost. We DO NOT log
prompt/completion text — these can carry PII. The customer_id is stored
as a 12-char SHA-256 prefix so it can be correlated across rows without
being directly identifiable.
"""
from __future__ import annotations

import hashlib

from app.llm_gateway.schemas import LLMResponse, NodePolicy
from app.persistence.repositories import LLMUsageRepository

_repo = LLMUsageRepository()


def hash_customer(customer_id: str | None) -> str | None:
    if not customer_id:
        return None
    return hashlib.sha256(customer_id.encode("utf-8")).hexdigest()[:12]


def log_usage(
    *,
    session_id: str | None,
    customer_id: str | None,
    conversation_step: str | None,
    policy: NodePolicy,
    response: LLMResponse,
    estimated_cost_usd: float,
) -> None:
    try:
        _repo.write(
            session_id=session_id,
            customer_id_hash=hash_customer(customer_id),
            conversation_step=conversation_step,
            node_purpose=policy.name,
            model_name=response.model_name,
            provider=response.provider,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=response.latency_ms,
            litellm_call_id=response.litellm_call_id,
            fallback_used=response.fallback_used,
            trimmed_context_count=response.trimmed_context_count,
        )
    except Exception:
        # Logging must never break the request path.
        pass
