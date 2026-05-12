from __future__ import annotations


class GatewayError(Exception):
    """Base class for gateway-related failures."""


class BudgetExceededError(GatewayError):
    """Raised when estimated input tokens exceed the node's hard budget
    even after context trimming. The caller MUST fall back to a safe
    response — we never let the call go through and incur cost.
    """


class RoutingError(GatewayError):
    """Unknown node_purpose or no model registered for the alias."""


class ProviderError(GatewayError):
    """Upstream LiteLLM / model server returned an error."""


class CloudFallbackDisabledError(GatewayError):
    """A cloud fallback was attempted while ``ENABLE_CLOUD_FALLBACK=false``."""
