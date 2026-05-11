from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep, FinanceType
from app.domain.schemas import ChatAction
from app.domain.tckn import mask_tckn
from app.security.audit import EVENT_SUMMARY_SHOWN, audit


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}".replace(",", ".") + " TL"


def summary_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    fields = state.fields
    if fields.finance_type is None:
        return graph_state

    lines: list[str] = []
    lines.append("Taşıt finansmanı ön başvuru bilgilerinizi özetliyorum:")
    if fields.finance_type == FinanceType.NEW:
        lines.append(f"- Finansman türü: Yeni taşıt")
        lines.append(f"- Araç modeli: {fields.vehicle_model or '-'}")
        lines.append(f"- Proforma fatura değeri: {_fmt_amount(fields.invoice_value)}")
        lines.append(f"- Talep edilen finansman tutarı: {_fmt_amount(fields.requested_amount)}")
        if fields.guarantor_tckn:
            lines.append(f"- Kefil TCKN: {mask_tckn(fields.guarantor_tckn)}")
    else:
        lines.append(f"- Finansman türü: İkinci el taşıt")
        lines.append(f"- Araç kasko değeri: {_fmt_amount(fields.casco_value)}")
        if fields.registration_date:
            lines.append(f"- Tescil tarihi: {fields.registration_date.isoformat()}")
        if fields.vehicle_age is not None:
            note = " (yaklaşık)" if fields.approximate_age_requires_confirmation else ""
            lines.append(f"- Araç yaşı: {fields.vehicle_age}{note}")
        lines.append(f"- Talep edilen finansman tutarı: {_fmt_amount(fields.requested_amount)}")
        if fields.seller_tckn:
            lines.append(f"- Satıcı TCKN: {mask_tckn(fields.seller_tckn)}")
        elif fields.seller_tckn_intent_skipped:
            lines.append("- Satıcı TCKN: Daha sonra paylaşılacak")
        else:
            lines.append("- Satıcı TCKN: Paylaşılmadı (opsiyonel)")

    if state.last_validation and state.last_validation.max_allowed_amount is not None:
        lines.append(
            f"- Maksimum talep edilebilecek tutar: "
            f"{_fmt_amount(state.last_validation.max_allowed_amount)}"
        )

    lines.append("\nBu bilgilerle ön başvuru kaydı oluşturulacaktır. Onaylıyor musunuz?")
    graph_state.add_reply("\n".join(lines))
    graph_state.add_action(ChatAction(type=ActionType.SHOW_SUMMARY))
    state.current_step = ConversationStep.AWAITING_CONFIRMATION

    audit(
        EVENT_SUMMARY_SHOWN,
        session_id=state.session_id,
        customer_id=state.customer_id,
        payload={
            "finance_type": fields.finance_type.value,
            "requested_amount": fields.requested_amount,
        },
    )
    return graph_state
