from __future__ import annotations

from app.config import get_settings
from app.rag.retriever import FaqRetriever
from app.chatbot.prompts import SYSTEM_FAQ_ANSWER


class FaqAnswerer:
    """Generates an FAQ answer from retrieved context.

    Three paths:
      - mock (no LLM) → return top retrieved chunk with citation
      - gateway enabled → route through LiteLLM with the ``faq_answer``
        node policy (large model, 3500/700 budget, up to 4 chunks)
      - legacy direct ChatOpenAI → kept for backwards compatibility
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._retriever = FaqRetriever.instance()
        self._llm = None
        if (
            self._settings.llm_provider != "mock"
            and not self._settings.llm_gateway_enabled
        ):
            try:
                from langchain_openai import ChatOpenAI

                self._llm = ChatOpenAI(
                    model=self._settings.llm_model,
                    base_url=self._settings.llm_base_url,
                    api_key=self._settings.llm_api_key,
                    temperature=self._settings.llm_temperature,
                )
            except Exception:
                self._llm = None

    def answer(
        self,
        question: str,
        k: int = 3,
        *,
        session_id: str | None = None,
        customer_id: str | None = None,
        conversation_step: str | None = None,
    ) -> str:
        ctx = self._retriever.search(question, k=k)
        if not ctx.hits:
            # No retrieved context → don't call LLM; return safe deterministic reply.
            return "Bu konuda dokümanda net bilgi bulamadım. Bir banka temsilcisi sizinle iletişime geçebilir."

        citation = ctx.citations()
        chunks = [h.document.text for h in ctx.hits]

        if self._settings.llm_gateway_enabled:
            try:
                from app.llm_gateway import (
                    BudgetExceededError,
                    get_gateway_client,
                )
                from app.llm_gateway.routing_policy import NODE_FAQ

                client = get_gateway_client()
                response = client.invoke(
                    node_purpose=NODE_FAQ,
                    system_prompt=SYSTEM_FAQ_ANSWER,
                    user_message=f"Soru: {question}\n\nCevabını yalnızca bağlama dayandır.",
                    context_chunks=chunks,
                    session_id=session_id,
                    customer_id=customer_id,
                    conversation_step=conversation_step,
                )
                text = response.content or ctx.hits[0].document.text.strip()
                if citation:
                    text += f"\n\nKaynak: {citation[0]}"
                return text
            except BudgetExceededError:
                # Don't call LLM beyond budget — return safe deterministic reply.
                pass
            except Exception:
                pass
            top = ctx.hits[0]
            citation_text = f"\n\nKaynak: {citation[0]}" if citation else ""
            return top.document.text.strip() + citation_text

        if self._llm is None:
            top = ctx.hits[0]
            citation_text = f"\n\nKaynak: {citation[0]}" if citation else ""
            return top.document.text.strip() + citation_text

        from langchain_core.messages import HumanMessage, SystemMessage

        context_text = ctx.as_prompt_context()
        try:
            result = self._llm.invoke(
                [
                    SystemMessage(content=SYSTEM_FAQ_ANSWER),
                    HumanMessage(
                        content=(
                            f"Bağlam:\n{context_text}\n\n"
                            f"Soru: {question}\n\n"
                            "Cevabını yalnızca bağlama dayandır."
                        )
                    ),
                ]
            )
            text = result.content if hasattr(result, "content") else str(result)
            if citation:
                text += f"\n\nKaynak: {citation[0]}"
            return text
        except Exception:
            top = ctx.hits[0]
            citation_text = f"\n\nKaynak: {citation[0]}" if citation else ""
            return top.document.text.strip() + citation_text
