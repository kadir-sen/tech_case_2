from __future__ import annotations

from app.chatbot.chains.faq_chain import FaqAnswerer
from app.chatbot.state import GraphState
from app.domain.enums import ActionType, IntentType
from app.domain.schemas import ChatAction


_answerer: FaqAnswerer | None = None


def _get_answerer() -> FaqAnswerer:
    global _answerer
    if _answerer is None:
        _answerer = FaqAnswerer()
    return _answerer


def faq_router_node(graph_state: GraphState) -> GraphState:
    """If the user's message is an FAQ question, answer from RAG and DO NOT
    mutate the application state. We only set a reply.
    """
    extracted = graph_state.extracted
    if extracted is None or extracted.intent != IntentType.FAQ_QUESTION:
        return graph_state

    question = extracted.faq_question or graph_state.user_message
    answer = _get_answerer().answer(question, k=3)
    graph_state.add_reply(answer)
    graph_state.add_action(ChatAction(type=ActionType.FAQ_ANSWER))
    graph_state.metadata["faq_answered"] = True
    return graph_state
