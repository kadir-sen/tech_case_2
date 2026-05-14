import uuid

from app.domain.enums import ConversationStep, FinanceType
from tests._helpers import accept_consent, send_message
from tests.conftest import VALID_TCKN_GUARANTOR


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_new_vehicle_happy_path_persists_application():
    sid = _sid("new-happy")
    accept_consent(sid)

    reply, state = send_message(
        sid,
        "Yeni araç için başvuru yapacağım. Aracın proforma fatura değeri 4 milyon TL, "
        "Toyota Corolla model, 2 milyon TL finansman istiyorum.",
    )
    assert state.fields.finance_type == FinanceType.NEW
    assert state.current_step == ConversationStep.AWAITING_CONFIRMATION
    assert "ön başvuru" in reply.lower() or "özet" in reply.lower()

    reply2, state2 = send_message(sid, "Evet, onaylıyorum")
    assert state2.application_id is not None
    assert state2.current_step == ConversationStep.AWAITING_HGS_DECISION
    assert "HGS" in reply2 or "hgs" in reply2.lower()


def test_new_vehicle_over_7m_rejected_before_confirmation():
    sid = _sid("new-over7m")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "Yeni araç almak istiyorum. Fatura değeri 8 milyon TL, Toyota Corolla, 4 milyon finansman istiyorum.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX
    assert state.application_id is None
    assert "7" in reply


def test_new_vehicle_5m_requires_guarantor_then_proceeds():
    sid = _sid("new-5m")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "Yeni araç için başvuru yapacağım. Fatura değeri 6 milyon, Toyota Corolla, 3 milyon finansman istiyorum.",
    )
    assert state.fields.finance_type == FinanceType.NEW
    # Either we're being asked for guarantor or we’re at the collection step.
    assert state.current_step in (ConversationStep.COLLECTING_FIELDS, ConversationStep.AWAITING_FIELD_FIX)
    assert "kefil" in reply.lower()

    reply2, state2 = send_message(sid, f"Kefil TCKN: {VALID_TCKN_GUARANTOR}")
    assert state2.current_step == ConversationStep.AWAITING_CONFIRMATION
    assert state2.fields.guarantor_tckn == VALID_TCKN_GUARANTOR


def test_new_vehicle_commercial_model_rejected():
    sid = _sid("new-commercial")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "Yeni araç başvurusu. Ford Transit, 3 milyon fatura, 1 milyon finansman istiyorum.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX
    assert any("ticari" in e.lower() for e in (state.last_validation.errors if state.last_validation else []))


def test_new_vehicle_60_percent_limit_then_fix():
    sid = _sid("new-60limit")
    accept_consent(sid)
    reply, state = send_message(
        sid,
        "Yeni araç. Toyota Corolla, fatura 4 milyon TL, 3 milyon finansman istiyorum.",
    )
    assert state.current_step == ConversationStep.AWAITING_FIELD_FIX

    reply2, state2 = send_message(sid, "Tutarı 2 milyon yap")
    assert state2.fields.requested_amount == 2_000_000
    assert state2.current_step == ConversationStep.AWAITING_CONFIRMATION


