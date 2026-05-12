"""LLM Gateway client — single entry point for every inference call.

Responsibilities:
  - Resolve the routing policy from ``node_purpose``.
  - Pre-call: estimate prompt tokens, trim context to budget.
  - Pre-call hard-stop if still over budget — fall back to a safe reply.
  - Dispatch via LiteLLM (OpenAI-compatible HTTP); never directly to a
    model server.
  - On provider failure, try the policy's ``fallback_alias`` once.
  - Cloud fallback only when ``ENABLE_CLOUD_FALLBACK=true``.
  - Post-call: structured usage logging (token-only; never raw text).

The gateway is intentionally test-friendly: pass an explicit ``backend``
to the constructor and exercise budget/routing/logging without any
running LiteLLM container.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app.config import get_settings
from app.llm_gateway.budget import fit_to_budget
from app.llm_gateway.exceptions import (
    BudgetExceededError,
    CloudFallbackDisabledError,
    ProviderError,
)
from app.llm_gateway.routing_policy import get_policy
from app.llm_gateway.schemas import LLMResponse, NodePolicy, TokenUsage
from app.llm_gateway.token_counter import count_tokens
from app.llm_gateway.usage_logger import log_usage


# Placeholder per-1K-token prices. Real values come from LiteLLM's
# ``model_info.input_cost_per_token`` / ``output_cost_per_token`` in
# infra/litellm/config.yaml — we copy them here for offline estimation.
_RATE_TABLE_USD_PER_1K: dict[str, tuple[float, float]] = {
    "vehicle-finance-small": (0.00010, 0.00020),
    "vehicle-finance-large": (0.00060, 0.00120),
    "vehicle-finance-guard": (0.00005, 0.00010),
    "cloud-fallback-large": (0.00300, 0.00900),
}

# Cloud-tagged aliases (must be in LiteLLM config to be routable). Used
# to enforce ENABLE_CLOUD_FALLBACK.
_CLOUD_ALIASES: frozenset[str] = frozenset({"cloud-fallback-large"})


Backend = Callable[[NodePolicy, str, str, list[str]], LLMResponse]


def _default_litellm_backend(
    policy: NodePolicy,
    system_prompt: str,
    user_message: str,
    context_chunks: list[str],
) -> LLMResponse:
    """Call LiteLLM via LangChain ChatOpenAI. Returns parsed LLMResponse."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    full_system = system_prompt
    if context_chunks:
        full_system += "\n\nReference context:\n" + "\n---\n".join(context_chunks)

    chat = ChatOpenAI(
        model=policy.model_alias,
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_virtual_key,
        temperature=policy.temperature,
        timeout=settings.llm_request_timeout_s,
        max_retries=1,
        max_tokens=policy.max_output_tokens,
    )
    start = time.perf_counter()
    try:
        msg = chat.invoke(
            [SystemMessage(content=full_system), HumanMessage(content=user_message)]
        )
    except Exception as exc:
        raise ProviderError(f"LiteLLM call failed for {policy.model_alias}: {exc}") from exc
    latency_ms = int((time.perf_counter() - start) * 1000)

    content = getattr(msg, "content", "")
    if isinstance(content, list):
        content = "".join(str(c) for c in content)

    meta = getattr(msg, "usage_metadata", None) or {}
    prompt_tokens = int(meta.get("input_tokens") or count_tokens(full_system + "\n" + user_message))
    completion_tokens = int(meta.get("output_tokens") or count_tokens(content))
    total = int(meta.get("total_tokens") or prompt_tokens + completion_tokens)

    return LLMResponse(
        content=content,
        usage=TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total),
        model_name=policy.model_alias,
        provider="litellm",
        latency_ms=latency_ms,
        litellm_call_id=getattr(msg, "id", None),
    )


class LLMGatewayClient:
    def __init__(self, *, backend: Backend | None = None) -> None:
        self._settings = get_settings()
        self._backend = backend or _default_litellm_backend

    @property
    def enabled(self) -> bool:
        return self._settings.llm_gateway_enabled

    def estimate_cost_usd(
        self, model_alias: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        p_rate, c_rate = _RATE_TABLE_USD_PER_1K.get(model_alias, (0.0, 0.0))
        return round((prompt_tokens * p_rate + completion_tokens * c_rate) / 1000.0, 6)

    def invoke(
        self,
        *,
        node_purpose: str,
        system_prompt: str,
        user_message: str,
        context_chunks: list[str] | None = None,
        history_messages: list[str] | None = None,
        session_id: str | None = None,
        customer_id: str | None = None,
        conversation_step: str | None = None,
    ) -> LLMResponse:
        policy = get_policy(node_purpose)

        # Cloud routing guard — must come BEFORE provider call.
        if policy.model_alias in _CLOUD_ALIASES and not self._settings.enable_cloud_fallback:
            raise CloudFallbackDisabledError(
                f"node {node_purpose!r} requested cloud alias {policy.model_alias!r} but cloud fallback is disabled"
            )

        fit = fit_to_budget(
            policy=policy,
            system_prompt=system_prompt,
            user_message=user_message,
            context_chunks=context_chunks,
            history_messages=history_messages,
        )

        if fit.estimated_prompt_tokens > policy.max_input_tokens:
            raise BudgetExceededError(
                f"{node_purpose}: estimated_prompt_tokens={fit.estimated_prompt_tokens} "
                f"> hard limit {policy.max_input_tokens} even after trimming"
            )

        try:
            response = self._backend(
                policy, system_prompt, user_message, fit.chunks_kept
            )
            response.trimmed_context_count = fit.chunks_dropped
        except ProviderError:
            response = self._try_fallback(
                policy=policy,
                system_prompt=system_prompt,
                user_message=user_message,
                chunks_kept=fit.chunks_kept,
                trimmed_context_count=fit.chunks_dropped,
            )

        cost = self.estimate_cost_usd(
            response.model_name, response.usage.prompt_tokens, response.usage.completion_tokens
        )
        log_usage(
            session_id=session_id,
            customer_id=customer_id,
            conversation_step=conversation_step,
            policy=policy,
            response=response,
            estimated_cost_usd=cost,
        )
        return response

    def _try_fallback(
        self,
        *,
        policy: NodePolicy,
        system_prompt: str,
        user_message: str,
        chunks_kept: list[str],
        trimmed_context_count: int,
    ) -> LLMResponse:
        if not policy.fallback_alias or policy.fallback_alias == policy.model_alias:
            raise ProviderError(f"{policy.name}: no fallback available")
        fb_policy = NodePolicy(
            name=policy.name,
            model_alias=policy.fallback_alias,
            max_input_tokens=policy.max_input_tokens,
            max_output_tokens=policy.max_output_tokens,
            max_context_chunks=policy.max_context_chunks,
            temperature=policy.temperature,
            fallback_alias=None,
        )
        if fb_policy.model_alias in _CLOUD_ALIASES and not self._settings.enable_cloud_fallback:
            raise CloudFallbackDisabledError(
                f"fallback {fb_policy.model_alias!r} blocked: cloud fallback disabled"
            )
        response = self._backend(fb_policy, system_prompt, user_message, chunks_kept)
        response.fallback_used = True
        response.trimmed_context_count = trimmed_context_count
        return response


_singleton: LLMGatewayClient | None = None


def get_gateway_client() -> LLMGatewayClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMGatewayClient()
    return _singleton


def reset_gateway_client_for_tests() -> None:
    global _singleton
    _singleton = None
