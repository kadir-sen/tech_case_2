from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep, FinanceType
from app.domain.schemas import ChatAction


_FIELD_PROMPTS: dict[str, str] = {
    "invoice_value": "Aracın proforma fatura değerini paylaşır mısınız? (örn. 4 milyon TL)",
    "casco_value": "Aracın kasko değerini paylaşır mısınız? (örn. 2,4 milyon TL)",
    "vehicle_model": "Aracın model adını paylaşır mısınız? (örn. Toyota Corolla)",
    "vehicle_model_clarification": (
        "Belirttiğiniz araç modelini katalogumuzda eşleştiremedim. "
        "Marka ve model adını tam olarak yazar mısınız? (örn. Renault Megane)"
    ),
    "requested_amount": "Talep ettiğiniz finansman tutarını paylaşır mısınız? (örn. 2 milyon TL)",
    "guarantor_tckn": (
        "Bu başvuru için kefil TCKN bilgisi gerekiyor. Kefilin 11 haneli "
        "TCKN bilgisini paylaşır mısınız?"
    ),
    "registration_date": (
        "Araç yaşını net hesaplayabilmem için ruhsat/tescil tarihini paylaşır mısınız? "
        "(örn. 12.05.2021)"
    ),
}


def collection_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    fields = state.fields

    # If finance type not yet known, ask first.
    if fields.finance_type is None:
        state.current_step = ConversationStep.AWAITING_FINANCE_TYPE
        graph_state.add_reply(
            "Taşıt finansmanı ön başvurusu için size yardımcı olabilirim. "
            "Yeni araç mı yoksa ikinci el araç için mi başvuru yapmak istiyorsunuz?"
        )
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
        prompt = _FIELD_PROMPTS.get(first, f"Lütfen {first} bilgisini paylaşır mısınız?")
        graph_state.add_reply(prompt)
        graph_state.add_action(ChatAction(type=ActionType.ASK_FIELD, field=first))
        return graph_state

    return graph_state


def finance_type_branch(fields_finance_type: FinanceType | None) -> str:
    return "ask_finance_type" if fields_finance_type is None else "validate"
