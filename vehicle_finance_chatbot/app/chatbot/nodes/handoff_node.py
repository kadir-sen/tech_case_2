from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep
from app.domain.schemas import ChatAction
from app.security.audit import EVENT_HANDOFF, audit


def handoff_node(graph_state: GraphState, reason: str) -> GraphState:
    state = graph_state.state
    state.current_step = ConversationStep.HANDOFF
    state.handoff_reason = reason
    audit(
        EVENT_HANDOFF,
        session_id=state.session_id,
        customer_id=state.customer_id,
        payload={"reason": reason},
    )
    graph_state.add_reply(
        "Sizi canlı bir banka temsilcisine yönlendirebilirim. Talebiniz iletilmiştir."
    )
    graph_state.add_action(ChatAction(type=ActionType.HANDOFF, payload={"reason": reason}))
    return graph_state
