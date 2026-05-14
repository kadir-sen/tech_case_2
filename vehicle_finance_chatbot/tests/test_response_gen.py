"""response_gen.py deterministic fallback testleri.

Gateway disabled (default) durumda response_gen LLM çağırmaz, deterministic
fallback metni döndürür. Bu testler fallback formatını + içerik
correctness'ini doğrular.
"""
from app.chatbot.response_gen import (
    render_collection_prompt,
    render_finance_type_prompt,
    render_validation_response,
)
from app.domain.enums import FinanceType
from app.domain.schemas import ApplicationFields, ValidationResult


def test_validation_fallback_contains_max_allowed():
    fields = ApplicationFields(
        finance_type=FinanceType.NEW,
        vehicle_model="Toyota Corolla",
        invoice_value=4_000_000,
        requested_amount=3_000_000,
    )
    result = ValidationResult(
        is_valid=False,
        errors=["Talep ettiğiniz 3.000.000 TL bu limiti aşıyor."],
        max_allowed_amount=2_400_000,
    )
    reply = render_validation_response(result, fields)
    assert "2.400.000" in reply
    assert "güncellemek" in reply.lower() or "güncelle" in reply.lower()


def test_validation_fallback_includes_max_when_missing_from_errors():
    fields = ApplicationFields(
        finance_type=FinanceType.USED,
        casco_value=4_000_000,
        requested_amount=2_000_000,
    )
    result = ValidationResult(
        is_valid=False,
        errors=["Tutar limiti aşıyor."],
        max_allowed_amount=1_600_000,
    )
    reply = render_validation_response(result, fields)
    assert "1.600.000" in reply


def test_collection_fallback_for_guarantor_mentions_threshold():
    fields = ApplicationFields(
        finance_type=FinanceType.NEW,
        vehicle_model="Toyota Corolla",
        invoice_value=6_000_000,
        requested_amount=3_000_000,
    )
    prompt = render_collection_prompt(
        "guarantor_tckn",
        fields,
        requires_guarantor=True,
    )
    assert "kefil" in prompt.lower()
    assert "tckn" in prompt.lower()


def test_collection_fallback_for_registration_date_has_example():
    fields = ApplicationFields(finance_type=FinanceType.USED, casco_value=2_400_000)
    prompt = render_collection_prompt("registration_date", fields)
    assert "tescil" in prompt.lower() or "ruhsat" in prompt.lower()


def test_finance_type_prompt_asks_clearly():
    prompt = render_finance_type_prompt()
    assert "yeni" in prompt.lower()
    assert "ikinci el" in prompt.lower()
