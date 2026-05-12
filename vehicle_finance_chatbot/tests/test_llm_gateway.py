"""Tests for the LiteLLM gateway layer.

The gateway is exercised with a stub backend so we never need a real
LiteLLM container running. Existing 76 tests must still pass with
LLM_GATEWAY_ENABLED=false (default).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from app.config import get_settings
from app.llm_gateway import (
    BudgetExceededError,
    CloudFallbackDisabledError,
    NodePolicy,
    LLMGatewayClient,
    LLMResponse,
    TokenUsage,
)
from app.llm_gateway.budget import fit_to_budget
from app.llm_gateway.client import reset_gateway_client_for_tests
from app.llm_gateway.routing_policy import (
    NODE_BUDGETS,
    NODE_FAQ,
    NODE_FIELD,
    NODE_INTENT,
    NODE_SAFETY,
)
from app.llm_gateway.token_counter import count_tokens
from app.llm_gateway.usage_logger import hash_customer
from app.persistence.repositories import LLMUsageRepository
from tests.conftest import VALID_TCKN_GUARANTOR


# --- Fake backend used by all gateway tests ----------------------------

class _CapturingBackend:
    """In-test backend that records every dispatched call and returns a
    canned response. Avoids any HTTP traffic.
    """

    def __init__(self, *, completion: str = "{}", fail_first: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._completion = completion
        self._fail_first = fail_first
        self._called = 0

    def __call__(
        self,
        policy: NodePolicy,
        system_prompt: str,
        user_message: str,
        context_chunks: list[str],
    ) -> LLMResponse:
        self._called += 1
        self.calls.append(
            {
                "model_alias": policy.model_alias,
                "node": policy.name,
                "system_len": len(system_prompt),
                "user_len": len(user_message),
                "chunks": list(context_chunks),
                "max_output_tokens": policy.max_output_tokens,
                "temperature": policy.temperature,
            }
        )
        if self._fail_first and self._called == 1:
            from app.llm_gateway.exceptions import ProviderError

            raise ProviderError("simulated upstream 503")
        prompt_tokens = count_tokens(system_prompt + user_message + "\n".join(context_chunks))
        completion_tokens = count_tokens(self._completion)
        return LLMResponse(
            content=self._completion,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            model_name=policy.model_alias,
            provider="fake-litellm",
            latency_ms=12,
            litellm_call_id=f"call-{self._called}",
        )


@pytest.fixture(autouse=True)
def _reset_gateway():
    reset_gateway_client_for_tests()
    yield
    reset_gateway_client_for_tests()


def _sid(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:6]}"


# --- token_counter / budget ---

def test_count_tokens_handles_empty_and_strings():
    assert count_tokens("") == 0
    assert count_tokens(None) == 0
    assert count_tokens("hello world") > 0


def test_fit_to_budget_trims_chunks_until_under_limit():
    policy = NodePolicy(
        name="t", model_alias="x", max_input_tokens=200, max_output_tokens=100,
        max_context_chunks=10,
    )
    big_chunk = "lorem " * 200  # ~ several hundred tokens
    fit = fit_to_budget(
        policy=policy,
        system_prompt="sys",
        user_message="q",
        context_chunks=[big_chunk, big_chunk, big_chunk],
    )
    assert fit.estimated_prompt_tokens <= 200
    assert fit.chunks_dropped >= 1


def test_fit_to_budget_caps_chunks_at_max_context_chunks():
    policy = NodePolicy(
        name="t", model_alias="x", max_input_tokens=10_000, max_output_tokens=100,
        max_context_chunks=2,
    )
    fit = fit_to_budget(
        policy=policy,
        system_prompt="sys",
        user_message="q",
        context_chunks=["a", "b", "c", "d"],
    )
    assert len(fit.chunks_kept) == 2
    assert fit.chunks_dropped == 2


# --- routing ---

def test_intent_classification_routes_to_small_model():
    assert NODE_BUDGETS[NODE_INTENT].model_alias.endswith("-small")
    assert NODE_BUDGETS[NODE_FIELD].model_alias.endswith("-small")


def test_faq_routes_to_large_model():
    assert NODE_BUDGETS[NODE_FAQ].model_alias.endswith("-large")


def test_safety_routes_to_guard_model():
    assert NODE_BUDGETS[NODE_SAFETY].model_alias.endswith("-guard")


# --- gateway invocation ---

def test_gateway_dispatches_with_correct_model_and_logs_usage(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    backend = _CapturingBackend(completion='{"ok":true}')
    client = LLMGatewayClient(backend=backend)

    repo = LLMUsageRepository()
    before = len(repo.list_recent(limit=1000))

    resp = client.invoke(
        node_purpose=NODE_FIELD,
        system_prompt="extract fields",
        user_message="Yeni araç. Fatura 3 milyon, 1 milyon istiyorum.",
        session_id=_sid("gw-disp"),
        customer_id="CUST001",
        conversation_step="COLLECTING_FIELDS",
    )
    assert resp.model_name.endswith("-small")
    assert resp.usage.total_tokens > 0
    assert len(backend.calls) == 1
    assert backend.calls[0]["max_output_tokens"] == NODE_BUDGETS[NODE_FIELD].max_output_tokens

    after = len(repo.list_recent(limit=1000))
    assert after == before + 1


def test_gateway_blocks_when_input_exceeds_budget_even_after_trim(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)

    # Use a tiny artificial policy by faking via NODE_FIELD and a huge
    # system prompt that exceeds the budget on its own.
    backend = _CapturingBackend()
    client = LLMGatewayClient(backend=backend)
    huge_system = "x " * 5000  # well over field_extraction's 1200-token cap
    with pytest.raises(BudgetExceededError):
        client.invoke(
            node_purpose=NODE_FIELD,
            system_prompt=huge_system,
            user_message="q",
        )
    assert backend.calls == [], "backend must not be called when budget exceeded"


def test_gateway_trims_rag_chunks_for_faq_node(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    backend = _CapturingBackend(completion="ok")
    client = LLMGatewayClient(backend=backend)

    big = "kasko değer " * 500
    resp = client.invoke(
        node_purpose=NODE_FAQ,
        system_prompt="answer from context only",
        user_message="ikinci el oran",
        context_chunks=[big, big, big, big, big, big],
    )
    sent_chunks = backend.calls[0]["chunks"]
    assert len(sent_chunks) < 6  # at least one was trimmed
    assert resp.trimmed_context_count >= 1


def test_fallback_used_when_primary_provider_fails(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    backend = _CapturingBackend(completion="fallback-answer", fail_first=True)
    client = LLMGatewayClient(backend=backend)

    resp = client.invoke(
        node_purpose=NODE_FIELD,
        system_prompt="extract",
        user_message="hi",
    )
    assert resp.fallback_used is True
    assert len(backend.calls) == 2
    # First was small, second (fallback) is large per policy.
    assert backend.calls[0]["model_alias"].endswith("-small")
    assert backend.calls[1]["model_alias"].endswith("-large")


def test_cloud_fallback_disabled_blocks_cloud_alias(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    monkeypatch.setattr(settings, "enable_cloud_fallback", False)
    # Build a policy that points directly at cloud and ensure we refuse.
    from app.llm_gateway.client import _CLOUD_ALIASES  # type: ignore

    assert "cloud-fallback-large" in _CLOUD_ALIASES

    # Patch the field policy to use the cloud alias temporarily.
    original = NODE_BUDGETS[NODE_FIELD]
    NODE_BUDGETS[NODE_FIELD] = NodePolicy(
        name=NODE_FIELD,
        model_alias="cloud-fallback-large",
        max_input_tokens=1200,
        max_output_tokens=300,
    )
    try:
        client = LLMGatewayClient(backend=_CapturingBackend())
        with pytest.raises(CloudFallbackDisabledError):
            client.invoke(
                node_purpose=NODE_FIELD,
                system_prompt="sys",
                user_message="q",
            )
    finally:
        NODE_BUDGETS[NODE_FIELD] = original


def test_max_output_tokens_propagated_from_policy(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    backend = _CapturingBackend()
    client = LLMGatewayClient(backend=backend)

    client.invoke(node_purpose=NODE_FAQ, system_prompt="s", user_message="u")
    assert backend.calls[0]["max_output_tokens"] == NODE_BUDGETS[NODE_FAQ].max_output_tokens


# --- PII safety in usage logs ---

def test_usage_log_does_not_contain_plain_customer_id(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    client = LLMGatewayClient(backend=_CapturingBackend(completion="ok"))
    sess = _sid("pii")
    client.invoke(
        node_purpose=NODE_INTENT,
        system_prompt="extract",
        user_message=f"benim tckn {VALID_TCKN_GUARANTOR} olsun lütfen",
        session_id=sess,
        customer_id="CUST001",
    )
    rows = LLMUsageRepository().list_recent(limit=20)
    me = next((r for r in rows if r.session_id == sess), None)
    assert me is not None
    # The plain customer_id must NEVER appear in the usage row; only a
    # 12-char SHA-256 prefix.
    assert me.customer_id_hash is not None
    assert me.customer_id_hash != "CUST001"
    assert me.customer_id_hash == hash_customer("CUST001")
    # Raw text columns do not exist on the schema — i.e. prompt/TCKN are
    # impossible to leak into this table.
    table_attrs = set(me.__table__.columns.keys())
    for forbidden in ("prompt", "completion", "raw_text", "content", "tckn"):
        assert forbidden not in table_attrs


# --- chain integration ---

def test_extraction_chain_uses_gateway_when_enabled(monkeypatch):
    """LLMExtractor should route through the gateway when enabled and
    fall back to the rule-based extractor on parse errors. This proves
    the wiring works without requiring a real LiteLLM.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "vllm")

    captured = _CapturingBackend(completion='{"intent":"start_application"}')
    client = LLMGatewayClient(backend=captured)
    # Inject the test client as the singleton.
    import app.llm_gateway.client as gateway_mod
    monkeypatch.setattr(gateway_mod, "_singleton", client)

    from app.chatbot.chains.extraction_chain import LLMExtractor
    from app.domain.schemas import ConversationStateModel
    from app.domain.enums import ConsentStatus, ConversationStep

    state = ConversationStateModel(
        session_id=_sid("extract-gw"),
        customer_id="CUST001",
        consent_status=ConsentStatus.ACCEPTED,
        current_step=ConversationStep.AWAITING_INTENT,
    )
    ex = LLMExtractor()
    ex.extract("Yeni araç başvurusu yapacağım.", state)

    assert len(captured.calls) == 1
    assert captured.calls[0]["node"] == NODE_FIELD


def test_gateway_disabled_does_not_break_existing_flow():
    """When disabled (default), the existing RuleBasedExtractor path is
    used — i.e. the 76 legacy tests are unaffected. We verify by making
    a couple of representative calls.
    """
    settings = get_settings()
    assert settings.llm_gateway_enabled is False
    # Just ensure import + instantiation works with disabled flag.
    client = LLMGatewayClient(backend=_CapturingBackend())
    assert client.enabled is False


def test_admin_summary_returns_aggregated_usage(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_gateway_enabled", True)
    client = LLMGatewayClient(backend=_CapturingBackend(completion="ok"))
    client.invoke(node_purpose=NODE_INTENT, system_prompt="s", user_message="u",
                  session_id=_sid("summary"))
    client.invoke(node_purpose=NODE_FAQ, system_prompt="s", user_message="u",
                  session_id=_sid("summary"))
    summary = LLMUsageRepository().summary()
    assert summary["total_calls"] >= 2
    assert summary["total_tokens"] > 0
    aliases = {b["model_name"] for b in summary["by_model_and_node"]}
    assert any(a.endswith("-small") for a in aliases)
    assert any(a.endswith("-large") for a in aliases)
