"""LiteLLM Gateway: governance layer for all LLM calls.

This module is the single chokepoint for inference. Every node calls the
gateway with a ``node_purpose`` (e.g. ``intent_classification``); the
gateway resolves the routing policy, applies a token budget, trims
context if needed, dispatches to LiteLLM (or a fallback), and logs
usage to ``llm_usage_logs``.

Business decisions stay in ``domain/rules.py`` — the gateway is purely
an inference governance layer.
"""
from app.llm_gateway.client import LLMGatewayClient, get_gateway_client  # noqa: F401
from app.llm_gateway.exceptions import (  # noqa: F401
    BudgetExceededError,
    CloudFallbackDisabledError,
    GatewayError,
    ProviderError,
    RoutingError,
)
from app.llm_gateway.routing_policy import NODE_BUDGETS, get_policy  # noqa: F401
from app.llm_gateway.schemas import LLMResponse, NodePolicy, TokenUsage  # noqa: F401
