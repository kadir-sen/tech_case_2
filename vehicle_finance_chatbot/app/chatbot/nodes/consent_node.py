from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConsentStatus, ConversationStep, IntentType
from app.domain.schemas import ChatAction
from app.security.audit import EVENT_CONSENT_ACCEPTED, EVENT_CONSENT_REJECTED, audit


CONSENT_PROMPT = (
    "Taşıt finansmanı ön başvuru sürecinde araç bilgileri ve gerekirse kefil/satıcı "
    "TCKN bilgisi gibi kişisel veriler işlenecektir. Bu veriler KVKK kapsamında "
    "yalnızca başvurunuz için kullanılacak ve banka iç güvenlik politikasına tabidir.\n\n"
    "Devam etmek için aydınlatma metnini kabul ediyor musunuz? (Evet / Hayır)"
)


def consent_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state

    if state.consent_status == ConsentStatus.ACCEPTED:
        return graph_state

    if state.consent_status == ConsentStatus.REJECTED:
        state.current_step = ConversationStep.SAFE_EXIT
        graph_state.add_reply(
            "Onayınız olmadan ön başvuru oluşturamıyoruz. Yine de taşıt finansmanı "
            "hakkında genel sorularınız varsa cevaplayabilirim."
        )
        return graph_state

    # NOT_ASKED or AWAITING_CONSENT
    intent = graph_state.extracted.intent if graph_state.extracted else IntentType.UNKNOWN
    if state.current_step == ConversationStep.START:
        state.current_step = ConversationStep.AWAITING_CONSENT
        # If user opened the chat with a substantive request, remember the
        # message so we can replay it after consent acceptance instead of
        # silently dropping it.
        if graph_state.extracted is not None and graph_state.extracted.intent in (
            IntentType.START_APPLICATION,
            IntentType.PROVIDE_INFO,
        ):
            state.pending_application_message = graph_state.user_message
        graph_state.add_reply(CONSENT_PROMPT)
        graph_state.add_action(ChatAction(type=ActionType.ASK_CONSENT))
        return graph_state

    if state.current_step == ConversationStep.AWAITING_CONSENT:
        if intent == IntentType.CONFIRM:
            state.consent_status = ConsentStatus.ACCEPTED
            state.current_step = ConversationStep.AWAITING_INTENT
            audit(
                EVENT_CONSENT_ACCEPTED,
                session_id=state.session_id,
                customer_id=state.customer_id,
            )
            # Replay the user's original first-turn message so we don't
            # ask them to repeat themselves.
            if state.pending_application_message:
                graph_state.user_message = state.pending_application_message
                state.pending_application_message = None
                from app.chatbot.nodes.intent_node import get_default_extractor

                graph_state.extracted = get_default_extractor().extract(
                    graph_state.user_message, state
                )
            return graph_state
        if intent == IntentType.REJECT:
            state.consent_status = ConsentStatus.REJECTED
            state.current_step = ConversationStep.SAFE_EXIT
            audit(
                EVENT_CONSENT_REJECTED,
                session_id=state.session_id,
                customer_id=state.customer_id,
            )
            graph_state.add_reply(
                "Onayınız alınmadığı için ön başvuru oluşturulamayacaktır. "
                "Genel bilgilendirme için sorularınız olursa yanıtlayabilirim."
            )
            return graph_state
        # Still unclear — re-ask.
        graph_state.add_reply(
            "Cevabınızı net anlayamadım. Aydınlatma metnini onaylıyor musunuz? (Evet / Hayır)"
        )
        graph_state.add_action(ChatAction(type=ActionType.ASK_CONSENT))
        return graph_state

    return graph_state
