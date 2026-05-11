from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep, IntentType
from app.domain.schemas import ChatAction
from app.persistence.repositories import HgsRepository
from app.security.audit import (
    EVENT_HGS_ACCEPTED,
    EVENT_HGS_OFFERED,
    EVENT_HGS_REJECTED,
    audit,
)


_repo = HgsRepository()


def hgs_offer_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    if state.hgs_offered:
        return graph_state
    state.hgs_offered = True
    state.current_step = ConversationStep.AWAITING_HGS_DECISION
    audit(
        EVENT_HGS_OFFERED,
        session_id=state.session_id,
        customer_id=state.customer_id,
    )
    graph_state.add_reply(
        "Aracınızla otoyol ve köprü geçişlerinde kullanılmak üzere HGS ürünümüzü de "
        "sunabiliriz. HGS başvurusu yapmak ister misiniz? (Evet / Hayır)"
    )
    graph_state.add_action(ChatAction(type=ActionType.OFFER_HGS))
    return graph_state


def hgs_decision_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    extracted = graph_state.extracted
    if extracted is None or extracted.intent != IntentType.HGS_DECISION:
        return graph_state

    accept = extracted.field_to_update == "hgs_accepted_yes"
    state.hgs_accepted = accept
    if state.application_id and state.customer_id:
        try:
            _repo.create_lead(
                customer_id=state.customer_id,
                application_id=state.application_id,
                interest=accept,
            )
        except Exception:
            pass
    state.current_step = ConversationStep.COMPLETED

    audit(
        EVENT_HGS_ACCEPTED if accept else EVENT_HGS_REJECTED,
        session_id=state.session_id,
        customer_id=state.customer_id,
        payload={"application_id": state.application_id},
    )
    if accept:
        graph_state.add_reply(
            "HGS başvurunuz alındı. Taşıt finansmanı sürecinizle birlikte "
            "değerlendirilecektir. Başka bir konuda yardımcı olabilir miyim?"
        )
    else:
        graph_state.add_reply(
            "HGS başvurusu yapılmayacak. Taşıt finansmanı ön başvurunuz oluşturuldu. "
            "Başka bir konuda yardımcı olabilir miyim?"
        )
    return graph_state
