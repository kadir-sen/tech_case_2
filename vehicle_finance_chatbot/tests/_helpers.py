from __future__ import annotations

from app.auth.mock_customer_store import get_customer
from app.chatbot.graph import run_turn
from app.chatbot.state import GraphState
from app.domain.schemas import ConversationStateModel
from app.persistence.repositories import ConversationRepository


_repo = ConversationRepository()


def send_message(
    session_id: str,
    message: str,
    *,
    customer_id: str = "CUST001",
    idempotency_key: str | None = None,
) -> tuple[str, ConversationStateModel]:
    state = _repo.load(session_id)
    customer = get_customer(customer_id)
    if state is None:
        state = ConversationStateModel(session_id=session_id, customer_id=customer_id)
    else:
        state.customer_id = customer_id

    gs = GraphState(
        user_message=message,
        state=state,
        customer=customer,
        idempotency_key=idempotency_key,
    )
    run_turn(gs)
    _repo.save(state)
    return gs.reply(), state


def accept_consent(session_id: str) -> ConversationStateModel:
    send_message(session_id, "merhaba")
    _, state = send_message(session_id, "Evet, kabul ediyorum")
    return state
