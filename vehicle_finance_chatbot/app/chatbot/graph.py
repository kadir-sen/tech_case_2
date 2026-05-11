"""LangGraph workflow for the vehicle finance chatbot.

We use LangGraph's ``StateGraph`` to orchestrate one conversation turn.
Each invocation maps a single user message + persisted state to a single
reply. The graph itself is stateless across turns; persistence lives in
``ConversationRepository``.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.chatbot.nodes.collection_node import collection_node
from app.chatbot.nodes.consent_node import consent_node
from app.chatbot.nodes.faq_router_node import faq_router_node
from app.chatbot.nodes.field_extraction_node import field_extraction_node
from app.chatbot.nodes.handoff_node import handoff_node
from app.chatbot.nodes.hgs_node import hgs_decision_node, hgs_offer_node
from app.chatbot.nodes.intent_node import intent_node
from app.chatbot.nodes.persistence_node import persistence_node
from app.chatbot.nodes.summary_node import summary_node
from app.chatbot.nodes.validation_node import validation_node
from app.chatbot.state import GraphState
from app.domain.enums import (
    ActionType,
    ConsentStatus,
    ConversationStep,
    IntentType,
)
from app.domain.schemas import ChatAction
from app.security.audit import EVENT_GUARDRAIL_TRIGGERED, audit
from app.security.guardrails import check_user_input


# --- Node wrappers around the shared GraphState dataclass ---

def n_load_session(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    if gs.customer is not None:
        gs.state.customer_id = gs.customer.customer_id
    return state


def n_guardrail(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    res = check_user_input(gs.user_message)
    if res.blocked:
        gs.guardrail_blocked = True
        gs.state.guardrail_triggered = True
        audit(
            EVENT_GUARDRAIL_TRIGGERED,
            session_id=gs.state.session_id,
            customer_id=gs.state.customer_id,
            payload={"reason": res.reason},
        )
        gs.add_reply(res.safe_reply or "Bu talebi karşılayamıyorum.")
        gs.add_action(ChatAction(type=ActionType.SAFE_REPLY))
    return state


def n_consent(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    consent_node(gs)
    return state


def n_intent(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    intent_node(gs)
    return state


def n_faq(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    faq_router_node(gs)
    return state


def n_apply_fields(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    field_extraction_node(gs)
    return state


def n_validate(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    validation_node(gs)
    return state


def n_collect(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    collection_node(gs)
    return state


def n_summary(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    summary_node(gs)
    return state


def n_persist(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    persistence_node(gs)
    return state


def n_hgs_offer(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    hgs_offer_node(gs)
    return state


def n_hgs_decision(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    hgs_decision_node(gs)
    return state


def n_cancel(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    gs.state.current_step = ConversationStep.SAFE_EXIT
    gs.add_reply(
        "Talebiniz üzerine başvuru süreci iptal edildi. İhtiyacınız olursa "
        "yeniden başvuru başlatabilirsiniz."
    )
    return state


def n_handoff(state: dict[str, Any]) -> dict[str, Any]:
    gs: GraphState = state["gs"]
    handoff_node(gs, gs.metadata.get("handoff_reason", "agent_requested"))
    return state


# --- Conditional routers ---

def route_after_guardrail(state: dict[str, Any]) -> str:
    gs: GraphState = state["gs"]
    if gs.guardrail_blocked:
        return "end"
    return "intent"


def route_after_consent(state: dict[str, Any]) -> str:
    gs: GraphState = state["gs"]
    # FAQ questions are allowed even without consent (general info only).
    if gs.extracted is not None and gs.extracted.intent == IntentType.FAQ_QUESTION:
        return "route_intent"
    if gs.state.consent_status == ConsentStatus.REJECTED:
        return "end"
    if gs.state.current_step == ConversationStep.AWAITING_CONSENT:
        return "end"
    return "route_intent"


def n_route_intent_passthrough(state: dict[str, Any]) -> dict[str, Any]:
    return state


def route_after_intent(state: dict[str, Any]) -> str:
    gs: GraphState = state["gs"]
    ex = gs.extracted
    step = gs.state.current_step

    if ex is None:
        return "apply_fields"

    if ex.intent == IntentType.FAQ_QUESTION:
        return "faq"
    if ex.intent == IntentType.CANCEL or (
        ex.intent == IntentType.REJECT and step != ConversationStep.AWAITING_HGS_DECISION
        and step != ConversationStep.AWAITING_CONFIRMATION
    ):
        return "cancel"
    if ex.intent == IntentType.HGS_DECISION and step == ConversationStep.AWAITING_HGS_DECISION:
        return "hgs_decision"
    if ex.intent == IntentType.CONFIRM and step == ConversationStep.AWAITING_CONFIRMATION:
        return "persist"
    if ex.intent == IntentType.REJECT and step == ConversationStep.AWAITING_CONFIRMATION:
        return "cancel"
    return "apply_fields"


def route_after_validation(state: dict[str, Any]) -> str:
    gs: GraphState = state["gs"]
    result = gs.state.last_validation
    if result is None:
        # Possibly because finance_type missing — go to collection.
        return "collect"
    if result.is_valid:
        return "summary"
    if result.errors:
        return "end"  # collection_node prompts already issued inside validation_node
    if result.missing_fields:
        return "collect"
    return "end"


def route_after_persist(state: dict[str, Any]) -> str:
    gs: GraphState = state["gs"]
    if gs.state.application_id and gs.state.current_step == ConversationStep.PERSISTED:
        return "hgs_offer"
    return "end"


# --- Graph factory ---

def _build_graph():
    g = StateGraph(dict)

    g.add_node("load_session", n_load_session)
    g.add_node("guardrail", n_guardrail)
    g.add_node("consent", n_consent)
    g.add_node("intent", n_intent)
    g.add_node("faq", n_faq)
    g.add_node("apply_fields", n_apply_fields)
    g.add_node("validate", n_validate)
    g.add_node("collect", n_collect)
    g.add_node("summary", n_summary)
    g.add_node("persist", n_persist)
    g.add_node("hgs_offer", n_hgs_offer)
    g.add_node("hgs_decision", n_hgs_decision)
    g.add_node("cancel", n_cancel)
    g.add_node("handoff", n_handoff)

    g.add_edge(START, "load_session")
    g.add_edge("load_session", "guardrail")

    # Intent extraction always happens first so downstream nodes (including
    # consent) can branch on it.
    g.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {"end": END, "intent": "intent"},
    )

    g.add_edge("intent", "consent")

    g.add_conditional_edges(
        "consent",
        route_after_consent,
        {"end": END, "route_intent": "route_intent"},
    )

    g.add_node("route_intent", n_route_intent_passthrough)
    g.add_conditional_edges(
        "route_intent",
        route_after_intent,
        {
            "faq": "faq",
            "cancel": "cancel",
            "hgs_decision": "hgs_decision",
            "persist": "persist",
            "apply_fields": "apply_fields",
        },
    )

    g.add_edge("apply_fields", "validate")

    g.add_conditional_edges(
        "validate",
        route_after_validation,
        {"summary": "summary", "collect": "collect", "end": END},
    )

    g.add_edge("collect", END)
    g.add_edge("summary", END)
    g.add_edge("cancel", END)
    g.add_edge("faq", END)
    g.add_edge("handoff", END)

    g.add_conditional_edges(
        "persist",
        route_after_persist,
        {"hgs_offer": "hgs_offer", "end": END},
    )
    g.add_edge("hgs_offer", END)
    g.add_edge("hgs_decision", END)

    return g.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = _build_graph()
    return _compiled


def run_turn(gs: GraphState) -> GraphState:
    """Convenience wrapper executing one turn of the workflow."""
    graph = get_graph()
    graph.invoke({"gs": gs})
    return gs
