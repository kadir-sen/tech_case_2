"""Customer-bazlı token budget enforcement testleri."""
import uuid

import pytest

from app.config import get_settings
from app.llm_gateway.client import LLMGatewayClient
from app.llm_gateway.exceptions import CustomerBudgetExceededError
from app.llm_gateway.routing_policy import NODE_FIELD
from app.llm_gateway.schemas import LLMResponse, NodePolicy, TokenUsage


class _NoopBackend:
    def __init__(self, *, prompt_tokens: int = 100, completion_tokens: int = 50) -> None:
        self.calls = 0
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def __call__(self, policy: NodePolicy, system_prompt, user_message, context_chunks):
        self.calls += 1
        total = self._prompt_tokens + self._completion_tokens
        return LLMResponse(
            content="ok",
            usage=TokenUsage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                total_tokens=total,
            ),
            model_name=policy.model_alias,
            provider="test",
            latency_ms=1,
        )


def _invoke(client: LLMGatewayClient, customer_id: str) -> None:
    client.invoke(
        node_purpose=NODE_FIELD,
        system_prompt="sys",
        user_message="hi",
        session_id=f"sess-{uuid.uuid4().hex[:6]}",
        customer_id=customer_id,
        conversation_step="START",
    )


def test_customer_budget_blocks_after_hourly_quota(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_tokens_per_customer_hourly", 600)
    monkeypatch.setattr(settings, "max_tokens_per_customer_daily", 0)  # disable daily

    backend = _NoopBackend(prompt_tokens=200, completion_tokens=100)  # 300 / call
    client = LLMGatewayClient(backend=backend)
    customer = f"CUSTBUDGET-{uuid.uuid4().hex[:6]}"

    # 2 çağrı (600 token) → limite çıkar; 3. çağrı budget'ı aşmalı.
    _invoke(client, customer)
    _invoke(client, customer)

    with pytest.raises(CustomerBudgetExceededError) as exc:
        _invoke(client, customer)
    assert exc.value.window == "1h"
    assert exc.value.limit == 600


def test_customer_budget_zero_disables_check(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_tokens_per_customer_hourly", 0)
    monkeypatch.setattr(settings, "max_tokens_per_customer_daily", 0)

    backend = _NoopBackend()
    client = LLMGatewayClient(backend=backend)
    customer = f"CUSTBUDGET-{uuid.uuid4().hex[:6]}"

    for _ in range(5):
        _invoke(client, customer)
    assert backend.calls == 5
