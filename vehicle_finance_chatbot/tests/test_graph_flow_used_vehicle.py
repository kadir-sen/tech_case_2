import uuid

from app.domain.enums import ConversationStep, FinanceType
from tests._helpers import accept_consent, send_message


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_used_vehicle_happy_path():
    sid = _sid("used-happy")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "İkinci el araç için başvuru yapacağım. Kasko değeri 2,4 milyon, tescil tarihi "
        "12.05.2023, 900 bin finansman istiyorum.",
    )
    assert state.fields.finance_type == FinanceType.USED
    assert state.current_step == ConversationStep.AWAITING_CONFIRMATION
    assert state.fields.casco_value == 2_400_000
    assert state.fields.registration_date is not None


def test_used_age_over_5_rejected():
    sid = _sid("used-old")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "İkinci el araç, kasko değeri 2 milyon, tescil 01.01.2010, 500 bin finansman.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX
    assert any("5" in e for e in (state.last_validation.errors if state.last_validation else []))


def test_used_40_percent_limit_violation():
    sid = _sid("used-40pc")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "İkinci el araç, kasko değeri 4 milyon, tescil 01.06.2023, 2 milyon finansman istiyorum.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX
    # Max should be 1.6M
    assert any("1.600.000" in e for e in (state.last_validation.errors if state.last_validation else []))


def test_used_3m_upper_cap():
    sid = _sid("used-3mcap")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "İkinci el. Kasko değeri 10 milyon, tescil 01.06.2023, 4 milyon finansman istiyorum.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX
    assert state.last_validation is not None
    assert state.last_validation.max_allowed_amount == 3_000_000.0


def test_used_seller_tckn_optional_skip():
    sid = _sid("used-seller-skip")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "İkinci el araç, kasko 2 milyon, tescil 01.06.2023, 500 bin finansman. Satıcı TCKN sonra verebilirim.",
    )
    assert state.fields.seller_tckn_intent_skipped is True
    assert state.current_step == ConversationStep.AWAITING_CONFIRMATION
