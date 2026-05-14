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


class CustomerBudgetExceededError(GatewayError):
    """Customer's sliding-window token quota has been exhausted.

    Bu hatanın amacı sadece masraf koruması değil; kümülatif token tüketimi
    aniden artan kullanıcılar (chatbot'u sipariş asistanı yerine genel
    amaç LLM gibi kullanmaya çalışan abuse senaryoları) için **erken uyarı
    katmanı**dır. Aşıldığında caller kullanıcıya graceful bir mesaj döner
    ve audit'e yazar.
    """

    def __init__(self, message: str, *, window: str, used_tokens: int, limit: int) -> None:
        super().__init__(message)
        self.window = window
        self.used_tokens = used_tokens
        self.limit = limit
