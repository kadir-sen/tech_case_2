from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConsentStatus, ConversationStep, FinanceType
from app.domain.schemas import ChatAction
from app.persistence.repositories import ApplicationRepository
from app.security.audit import EVENT_APPLICATION_PERSISTED, audit
from app.security.idempotency import SCOPE_APPLICATION_CREATE, build_application_key


_repo = ApplicationRepository()


def persistence_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    fields = state.fields
    customer = graph_state.customer

    if state.consent_status != ConsentStatus.ACCEPTED:
        graph_state.add_reply(
            "Onayınız olmadan ön başvuru oluşturulamaz."
        )
        return graph_state

    if customer is None or state.customer_id is None:
        graph_state.add_reply(
            "Müşteri oturum bilgisi alınamadığı için ön başvuru oluşturulamadı. "
            "Lütfen mobil uygulamadan tekrar deneyiniz."
        )
        return graph_state

    if fields.finance_type is None or state.last_validation is None or not state.last_validation.is_valid:
        graph_state.add_reply("Başvuruyu oluşturmak için önce başvuru bilgileri doğrulanmalı.")
        return graph_state

    idem_key = build_application_key(state.session_id, graph_state.idempotency_key)
    row, created = _repo.create(
        customer_id=state.customer_id,
        session_id=state.session_id,
        finance_type=FinanceType(fields.finance_type.value),
        fields=fields,
        validation=state.last_validation,
        idempotency_scope=SCOPE_APPLICATION_CREATE,
        idempotency_key=idem_key,
    )
    state.application_id = row.application_id
    state.current_step = ConversationStep.PERSISTED

    audit(
        EVENT_APPLICATION_PERSISTED,
        session_id=state.session_id,
        customer_id=state.customer_id,
        payload={
            "application_id": row.application_id,
            "finance_type": fields.finance_type.value,
            "created": created,
            "duplicate_prevented": not created,
        },
    )

    if created:
        graph_state.add_reply(
            f"Ön başvurunuz başarıyla oluşturuldu. Başvuru numaranız: {row.application_id}"
        )
    else:
        graph_state.add_reply(
            f"Bu oturum için zaten ön başvuru oluşturulmuş. Başvuru numaranız: "
            f"{row.application_id}"
        )
    graph_state.add_action(ChatAction(type=ActionType.CONFIRM, payload={"application_id": row.application_id}))
    return graph_state
