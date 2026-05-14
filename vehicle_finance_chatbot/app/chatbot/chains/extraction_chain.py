"""LLM-first intent + field extraction.

Production yolu yalnızca ``LLMExtractor``. LLM gateway (LiteLLM) etkinse
çağrılar oradan yönlendirilir; aksi durumda legacy ChatOpenAI doğrudan
provider'a gider. Her iki yolda da Pydantic ``ExtractedFields`` structured
output beklenir.

Regex / keyword tabanlı rule-based extractor production'dan tamamen
kaldırıldı. Testler için deterministic stub `tests/_stub_extractor.py`
içinde tanımlıdır ve conftest tarafından monkeypatch ile enjekte edilir.
"""
from __future__ import annotations

import json
from typing import Any

from app.chatbot.prompts import SYSTEM_INTENT_EXTRACTION
from app.config import get_settings
from app.domain.schemas import ConversationStateModel, ExtractedFields


class LLMExtractor:
    """Structured intent + field extractor via the LiteLLM gateway.

    On any provider failure or invalid JSON output, returns an empty
    ``ExtractedFields(intent=UNKNOWN, confidence=0.0)`` so the chat path
    can render an "anlamadım, tekrarlar mısınız?" reply rather than
    crashing. Real production deployments should rely on gateway
    fallback aliases for high availability.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._direct_client = None  # lazy

    def _ensure_direct_client(self) -> None:
        if self._direct_client is not None:
            return
        from langchain_openai import ChatOpenAI

        settings = self._settings
        llm = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_request_timeout_s,
        )
        self._direct_client = llm.with_structured_output(ExtractedFields)

    def extract(self, message: str, state: ConversationStateModel) -> ExtractedFields:
        ctx: dict[str, Any] = {
            "current_step": state.current_step.value,
            "finance_type": state.fields.finance_type.value if state.fields.finance_type else None,
        }

        if self._settings.llm_gateway_enabled:
            return self._extract_via_gateway(message, state, ctx)
        return self._extract_direct(message, ctx)

    def _extract_via_gateway(
        self, message: str, state: ConversationStateModel, ctx: dict[str, Any]
    ) -> ExtractedFields:
        try:
            from app.llm_gateway import BudgetExceededError, get_gateway_client
            from app.llm_gateway.routing_policy import NODE_FIELD

            client = get_gateway_client()
            response = client.invoke(
                node_purpose=NODE_FIELD,
                system_prompt=SYSTEM_INTENT_EXTRACTION,
                user_message=f"context: {ctx}\nuser: {message}",
                session_id=state.session_id,
                customer_id=state.customer_id,
                conversation_step=state.current_step.value,
            )
            try:
                return ExtractedFields.model_validate(json.loads(response.content))
            except Exception:
                return _empty_extracted()
        except BudgetExceededError:
            return _empty_extracted()
        except Exception:
            return _empty_extracted()

    def _extract_direct(self, message: str, ctx: dict[str, Any]) -> ExtractedFields:
        from langchain_core.messages import HumanMessage, SystemMessage

        try:
            self._ensure_direct_client()
            result = self._direct_client.invoke(
                [
                    SystemMessage(content=SYSTEM_INTENT_EXTRACTION),
                    HumanMessage(content=f"context: {ctx}\nuser: {message}"),
                ]
            )
            if isinstance(result, ExtractedFields):
                return result
            return ExtractedFields.model_validate(result)
        except Exception:
            return _empty_extracted()


def _empty_extracted() -> ExtractedFields:
    from app.domain.enums import IntentType

    return ExtractedFields(intent=IntentType.UNKNOWN, confidence=0.0)


def get_extractor() -> LLMExtractor:
    """Factory used by ``intent_node``. Tests monkeypatch this to inject
    a deterministic stub; production code never sees the stub."""
    return LLMExtractor()
