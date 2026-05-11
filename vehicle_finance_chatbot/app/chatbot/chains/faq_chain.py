from __future__ import annotations

from app.config import get_settings
from app.rag.retriever import FaqRetriever
from app.chatbot.prompts import SYSTEM_FAQ_ANSWER


class FaqAnswerer:
    """Generates an FAQ answer from retrieved context.

    In mock mode we directly return the top retrieved chunk + heading
    citation. In LLM mode we ask the model to answer strictly from context.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._retriever = FaqRetriever.instance()
        self._llm = None
        if self._settings.llm_provider != "mock":
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

    def answer(self, question: str, k: int = 3) -> str:
        ctx = self._retriever.search(question, k=k)
        if not ctx.hits:
            return "Bu konuda dokümanda net bilgi bulamadım. Bir banka temsilcisi sizinle iletişime geçebilir."

        if self._llm is None:
            top = ctx.hits[0]
            citation = ctx.citations()
            citation_text = f"\n\nKaynak: {citation[0]}" if citation else ""
            return top.document.text.strip() + citation_text

        from langchain_core.messages import HumanMessage, SystemMessage

        context_text = ctx.as_prompt_context()
        citation = ctx.citations()
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
