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


def _build_summary_rows(graph_state: GraphState) -> list[dict]:
    """Inline-editable summary table — her satır bir başvuru alanı.

    UI bu payload'ı render eder: ``editable=True`` olan alanlar text-box
    olur; kullanıcı değişiklik yapıp ``edited_fields`` ile gönderir.
    Sistemce hesaplanmış alanlar (max_allowed_amount) editable=False.
    """
    state = graph_state.state
    fields = state.fields
    rows: list[dict] = []

    if fields.finance_type == FinanceType.NEW:
        rows.append(
            {"key": "finance_type", "label": "Finansman türü", "value": "Yeni taşıt", "editable": False, "type": "text"}
        )
        rows.append(
            {"key": "vehicle_model", "label": "Araç modeli", "value": fields.vehicle_model or "-", "editable": True, "type": "text"}
        )
        rows.append(
            {"key": "invoice_value", "label": "Proforma fatura değeri", "value": fields.invoice_value, "editable": True, "type": "currency", "currency": "TRY"}
        )
        rows.append(
            {"key": "requested_amount", "label": "Talep edilen finansman", "value": fields.requested_amount, "editable": True, "type": "currency", "currency": "TRY"}
        )
        if fields.guarantor_tckn:
            rows.append(
                {"key": "guarantor_tckn", "label": "Kefil TCKN", "value": mask_tckn(fields.guarantor_tckn), "editable": True, "type": "tckn"}
            )
    else:
        rows.append(
            {"key": "finance_type", "label": "Finansman türü", "value": "İkinci el taşıt", "editable": False, "type": "text"}
        )
        rows.append(
            {"key": "casco_value", "label": "Araç kasko değeri", "value": fields.casco_value, "editable": True, "type": "currency", "currency": "TRY"}
        )
        if fields.registration_date:
            rows.append(
                {"key": "registration_date", "label": "Tescil tarihi", "value": fields.registration_date.isoformat(), "editable": True, "type": "date"}
            )
        if fields.vehicle_age is not None:
            rows.append(
                {"key": "vehicle_age", "label": "Araç yaşı", "value": fields.vehicle_age, "editable": False, "type": "number"}
            )
        rows.append(
            {"key": "requested_amount", "label": "Talep edilen finansman", "value": fields.requested_amount, "editable": True, "type": "currency", "currency": "TRY"}
        )
        if fields.seller_tckn:
            rows.append(
                {"key": "seller_tckn", "label": "Satıcı TCKN", "value": mask_tckn(fields.seller_tckn), "editable": True, "type": "tckn"}
            )
        else:
            rows.append(
                {"key": "seller_tckn", "label": "Satıcı TCKN", "value": None, "editable": True, "type": "tckn", "placeholder": "Opsiyonel"}
            )

    if state.last_validation and state.last_validation.max_allowed_amount is not None:
        rows.append(
            {
                "key": "max_allowed_amount",
                "label": "Maksimum izinli tutar",
                "value": state.last_validation.max_allowed_amount,
                "editable": False,
                "type": "currency",
                "currency": "TRY",
                "hint": "Sistemce hesaplanmıştır",
            }
        )

    return rows


def _build_summary_text(rows: list[dict]) -> str:
    """Tablo render edemeyen istemciler için düz metin özet (fallback)."""
    lines = ["Taşıt finansmanı ön başvuru bilgilerinizi özetliyorum:"]
    for row in rows:
        val = row["value"]
        if val is None:
            display = "Paylaşılmadı"
        elif row["type"] == "currency" and isinstance(val, (int, float)):
            display = _fmt_amount(val)
        else:
            display = str(val)
        lines.append(f"- {row['label']}: {display}")
    lines.append("\nDeğişiklik yapmak isterseniz tablo üzerinden düzenleyebilirsiniz. Onaylıyor musunuz?")
    return "\n".join(lines)


def summary_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    if state.fields.finance_type is None:
        return graph_state

    rows = _build_summary_rows(graph_state)
    text = _build_summary_text(rows)
    graph_state.add_reply(text)
    graph_state.add_action(
        ChatAction(
            type=ActionType.SHOW_SUMMARY,
            payload={
                "fields": rows,
                "primary_action": {"label": "Onayla", "intent": "confirm"},
                "secondary_actions": [{"label": "İptal", "intent": "cancel"}],
            },
        )
    )
    state.current_step = ConversationStep.AWAITING_CONFIRMATION

    audit(
        EVENT_SUMMARY_SHOWN,
        session_id=state.session_id,
        customer_id=state.customer_id,
        payload={
            "finance_type": state.fields.finance_type.value,
            "requested_amount": state.fields.requested_amount,
        },
    )
    return graph_state
