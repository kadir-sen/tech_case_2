"""Greeting node testleri.

Greeting LLM gateway etkin değilse deterministic fallback'e düşer. Bu
test bu fallback yolunu doğrular — production'da LLM yolu kullanılır.
"""
import uuid

from app.auth.mock_customer_store import get_customer
from app.chatbot.nodes.greeting_node import greeting_node
from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep
from app.domain.schemas import ConversationStateModel


def _make_gs(customer_id: str = "CUST001") -> GraphState:
    customer = get_customer(customer_id)
    state = ConversationStateModel(
        session_id=f"sess-{uuid.uuid4().hex[:8]}",
        customer_id=customer_id,
    )
    return GraphState(user_message="", state=state, customer=customer)


def test_greeting_mentions_task_scope():
    gs = _make_gs()
    greeting_node(gs)
    reply = gs.reply()
    assert "taşıt finansmanı" in reply.lower()
    assert "yeni" in reply.lower()
    assert "ikinci el" in reply.lower()


def test_greeting_invites_open_questions():
    gs = _make_gs()
    greeting_node(gs)
    reply = gs.reply()
    # "Karar veremediyseniz danışabilirsiniz" tonu — FAQ kelimesi GEÇMEMELİ.
    assert "danış" in reply.lower() or "soru" in reply.lower()
    assert "faq" not in reply.lower()


def test_greeting_sets_greeted_step_and_action():
    gs = _make_gs()
    greeting_node(gs)
    assert gs.state.current_step == ConversationStep.GREETED
    types = [a.type for a in gs.actions]
    assert ActionType.SHOW_GREETING in types


def test_greeting_personalizes_with_customer_name():
    gs = _make_gs("CUST001")
    greeting_node(gs)
    reply = gs.reply()
    # CUST001 = "Ayşe Yılmaz"; greeting first-name içerir.
    assert "Ayşe" in reply
