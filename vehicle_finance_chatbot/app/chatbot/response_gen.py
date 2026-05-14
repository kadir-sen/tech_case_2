"""LLM-based natural-language renderers for deterministic outputs.

``app/domain/rules.py`` her zaman aynı structured ``ValidationResult``
üretmeye devam eder (limit, oran, missing fields, errors). Bu modül o
çıktıyı kullanıcı dostu Türkçe asistan mesajına çevirir. LLM'i karar
mekanizması olarak değil, **kelimeleştirici** olarak kullanırız.

LLM ulaşılamazsa deterministic fallback metni döner — kullanıcı yine de
backend'in ürettiği sayıları görür, sadece tonu robotik olur.
"""
from __future__ import annotations

from app.chatbot.prompts import SYSTEM_COLLECTION_PROMPT, SYSTEM_VALIDATION_RESPONSE
from app.config import get_settings
from app.domain.enums import FinanceType
from app.domain.schemas import ApplicationFields, ValidationResult


_FIELD_LABELS = {
    "finance_type": "Finansman türü",
    "invoice_value": "Proforma fatura değeri",
    "casco_value": "Araç kasko değeri",
    "vehicle_model": "Araç modeli",
    "requested_amount": "Talep edilen finansman",
    "registration_date": "Tescil tarihi",
    "vehicle_age": "Araç yaşı",
    "guarantor_tckn": "Kefil TCKN",
    "seller_tckn": "Satıcı TCKN",
}


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}".replace(",", ".") + " TL"


def _safe_llm_invoke(node_purpose: str, system_prompt: str, user_payload: str,
                     *, session_id: str | None, customer_id: str | None,
                     conversation_step: str | None) -> str | None:
    settings = get_settings()
    if not settings.llm_gateway_enabled:
        return None
    try:
        from app.llm_gateway import get_gateway_client

        client = get_gateway_client()
        response = client.invoke(
            node_purpose=node_purpose,
            system_prompt=system_prompt,
            user_message=user_payload,
            session_id=session_id,
            customer_id=customer_id,
            conversation_step=conversation_step,
        )
        text = (response.content or "").strip()
        return text or None
    except Exception:
        return None


def render_validation_response(
    validation: ValidationResult,
    fields: ApplicationFields,
    *,
    session_id: str | None = None,
    customer_id: str | None = None,
    conversation_step: str | None = None,
) -> str:
    """Limit / kefil / yaş / ticari hatalarını doğal Türkçe asistan diline çevirir.

    Backend deterministic çıktısı (errors + max_allowed_amount + missing_fields +
    requires_guarantor) LLM'e tasvir olarak verilir; LLM bunu kelimeleştirir.
    """
    payload_lines: list[str] = [
        f"finance_type: {fields.finance_type.value if fields.finance_type else 'unknown'}",
    ]
    if fields.vehicle_model:
        payload_lines.append(f"vehicle_model: {fields.vehicle_model}")
    if fields.invoice_value is not None:
        payload_lines.append(f"invoice_value: {fields.invoice_value}")
    if fields.casco_value is not None:
        payload_lines.append(f"casco_value: {fields.casco_value}")
    if fields.requested_amount is not None:
        payload_lines.append(f"requested_amount: {fields.requested_amount}")
    if validation.max_allowed_amount is not None:
        payload_lines.append(f"max_allowed_amount: {validation.max_allowed_amount}")
    if validation.requires_guarantor:
        payload_lines.append("requires_guarantor: true")
    payload_lines.append("errors:")
    for err in validation.errors:
        payload_lines.append(f"  - {err}")

    user_payload = (
        "Aşağıdaki deterministic validation çıktısını müşteriye yapıcı bir Türkçe "
        "mesajla aktar.\n\n" + "\n".join(payload_lines)
    )
    llm_out = _safe_llm_invoke(
        node_purpose="response_generation",
        system_prompt=SYSTEM_VALIDATION_RESPONSE,
        user_payload=user_payload,
        session_id=session_id,
        customer_id=customer_id,
        conversation_step=conversation_step,
    )
    if llm_out:
        return llm_out

    # Deterministic fallback: case'in kelimelerini kullan, mevcut hata cümleleri.
    pieces: list[str] = list(validation.errors)
    if validation.max_allowed_amount is not None and not any(
        "maksimum" in e.lower() for e in validation.errors
    ):
        pieces.append(
            f"Bu araç için maksimum {_fmt_amount(validation.max_allowed_amount)} "
            "finansman verilebilir."
        )
    pieces.append("Bilgileri güncellemek ister misiniz?")
    return " ".join(pieces)


def render_collection_prompt(
    missing_field: str,
    fields: ApplicationFields,
    *,
    requires_guarantor: bool = False,
    session_id: str | None = None,
    customer_id: str | None = None,
    conversation_step: str | None = None,
) -> str:
    """Tek bir eksik alan için müşteriye doğal bir soru cümlesi üretir."""
    payload_lines = [
        f"missing_field: {missing_field}",
        f"finance_type: {fields.finance_type.value if fields.finance_type else 'unknown'}",
    ]
    if fields.invoice_value is not None:
        payload_lines.append(f"invoice_value: {fields.invoice_value}")
    if fields.casco_value is not None:
        payload_lines.append(f"casco_value: {fields.casco_value}")
    if fields.vehicle_model:
        payload_lines.append(f"vehicle_model: {fields.vehicle_model}")
    if requires_guarantor:
        payload_lines.append("requires_guarantor: true (5M üzeri başvuru)")

    user_payload = (
        "Aşağıdaki context'e göre müşteriye eksik alanı sor. Tek doğal cümle:\n\n"
        + "\n".join(payload_lines)
    )
    llm_out = _safe_llm_invoke(
        node_purpose="response_generation",
        system_prompt=SYSTEM_COLLECTION_PROMPT,
        user_payload=user_payload,
        session_id=session_id,
        customer_id=customer_id,
        conversation_step=conversation_step,
    )
    if llm_out:
        return llm_out

    # Fallback: alan-bazlı sabit prompt'lar.
    return _FALLBACK_PROMPTS.get(missing_field, f"Lütfen {missing_field} bilgisini paylaşır mısınız?")


_FALLBACK_PROMPTS: dict[str, str] = {
    "invoice_value": "Aracın proforma fatura değerini paylaşır mısınız? (örn. 4 milyon TL)",
    "casco_value": "Aracın kasko değerini paylaşır mısınız? (örn. 2,4 milyon TL)",
    "vehicle_model": "Aracın model adını paylaşır mısınız? (örn. Toyota Corolla)",
    "requested_amount": "Talep ettiğiniz finansman tutarını paylaşır mısınız? (örn. 2 milyon TL)",
    "guarantor_tckn": (
        "5 milyon TL üzeri başvurularda kefil bilgisi gerekiyor. "
        "Kefilin 11 haneli TCKN bilgisini paylaşır mısınız?"
    ),
    "registration_date": (
        "Araç yaşını net hesaplayabilmem için ruhsat/tescil tarihini paylaşır mısınız? "
        "(örn. 12.05.2021)"
    ),
}


def render_finance_type_prompt() -> str:
    """İlk turn'de finance_type henüz yokken sorulacak cümle. Greeting'ten
    sonra kullanıcının ilk yanıtı şu ana kadar başvuru bilgisi içermiyorsa
    devreye girer. LLM çağrılmaz — kısa ve net bir soru."""
    return (
        "Yeni bir araç mı yoksa ikinci el bir araç mı için başvuru yapacaksınız? "
        "Bilgileri birlikte ilerletelim."
    )
