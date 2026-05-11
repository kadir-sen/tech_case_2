from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep, FinanceType
from app.domain.rules import validate_new_vehicle_application, validate_used_vehicle_application
from app.domain.schemas import ChatAction
from app.security.audit import EVENT_VALIDATION_FAILED, EVENT_VALIDATION_PASSED, audit


def validation_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    fields = state.fields

    if fields.finance_type is None:
        # Handled upstream.
        return graph_state

    state.current_step = ConversationStep.VALIDATING
    if fields.finance_type == FinanceType.NEW:
        result = validate_new_vehicle_application(fields)
    else:
        result = validate_used_vehicle_application(fields)

    state.last_validation = result
    graph_state.metadata["missing_fields"] = list(result.missing_fields)

    if result.is_valid:
        audit(
            EVENT_VALIDATION_PASSED,
            session_id=state.session_id,
            customer_id=state.customer_id,
            payload={
                "finance_type": fields.finance_type.value,
                "max_allowed_amount": result.max_allowed_amount,
            },
        )
        return graph_state

    if result.errors:
        audit(
            EVENT_VALIDATION_FAILED,
            session_id=state.session_id,
            customer_id=state.customer_id,
            payload={
                "finance_type": fields.finance_type.value,
                "errors": result.errors,
            },
        )
        state.current_step = ConversationStep.AWAITING_FIELD_FIX
        for err in result.errors:
            graph_state.add_reply(err)
        graph_state.add_reply(
            "Bilgileri güncellemek ister misiniz? Hangi alanı değiştireceğinizi yazabilirsiniz."
        )
        graph_state.add_action(ChatAction(type=ActionType.FIX_FIELD))
        return graph_state

    if result.missing_fields:
        state.current_step = ConversationStep.COLLECTING_FIELDS

    return graph_state
