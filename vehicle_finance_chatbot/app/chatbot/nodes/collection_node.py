from __future__ import annotations

from app.chatbot.response_gen import (
    render_collection_prompt,
    render_finance_type_prompt,
)
from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep, FinanceType
from app.domain.schemas import ChatAction


def collection_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    fields = state.fields

    # If finance type not yet known, ask first.
    if fields.finance_type is None:
        state.current_step = ConversationStep.AWAITING_FINANCE_TYPE
        graph_state.add_reply(render_finance_type_prompt())
        graph_state.add_action(ChatAction(type=ActionType.ASK_FINANCE_TYPE))
        return graph_state

    state.current_step = ConversationStep.COLLECTING_FIELDS

    if graph_state.metadata.get("invalid_guarantor_tckn"):
        graph_state.add_reply(
            "Paylaştığınız kefil TCKN bilgisi geçersiz görünüyor. "
            "Lütfen 11 haneli TCKN'yi kontrol edip tekrar yazar mısınız?"
        )
        graph_state.add_action(ChatAction(type=ActionType.ASK_FIELD, field="guarantor_tckn"))
        return graph_state

    if graph_state.metadata.get("invalid_seller_tckn"):
        graph_state.add_reply(
            "Satıcı TCKN bilgisi geçersiz görünüyor. Doğru TCKN'yi paylaşabilir veya "
            "bu bilgiyi sonra vereceğinizi belirtebilirsiniz."
        )
        graph_state.add_action(ChatAction(type=ActionType.ASK_FIELD, field="seller_tckn"))
        return graph_state

    missing = graph_state.metadata.get("missing_fields") or []
    if missing:
        first = missing[0]
        requires_guarantor = bool(
            state.last_validation and state.last_validation.requires_guarantor
        )
        prompt = render_collection_prompt(
            first,
            fields,
            requires_guarantor=requires_guarantor,
            session_id=state.session_id,
            customer_id=state.customer_id,
            conversation_step=state.current_step.value,
        )
        graph_state.add_reply(prompt)
        graph_state.add_action(ChatAction(type=ActionType.ASK_FIELD, field=first))
        return graph_state

    return graph_state


def finance_type_branch(fields_finance_type: FinanceType | None) -> str:
    return "ask_finance_type" if fields_finance_type is None else "validate"
