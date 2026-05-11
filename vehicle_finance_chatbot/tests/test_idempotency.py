import uuid

from app.domain.enums import ConversationStep
from tests._helpers import accept_consent, send_message


def test_double_confirmation_does_not_create_duplicate_application():
    sid = f"idem-{uuid.uuid4().hex[:8]}"
    accept_consent(sid)
    send_message(
        sid,
        "Yeni araç. Toyota Corolla, fatura 3 milyon, 1 milyon finansman istiyorum.",
    )
    _, state1 = send_message(sid, "Evet, onaylıyorum")
    app_id1 = state1.application_id
    assert app_id1 is not None

    # Second confirm (e.g. duplicate click or network retry).
    _, state2 = send_message(sid, "Evet")
    assert state2.application_id == app_id1


def test_explicit_idempotency_key_returns_same_app():
    sid = f"idem2-{uuid.uuid4().hex[:8]}"
    accept_consent(sid)
    send_message(
        sid,
        "Yeni araç başvurusu. Toyota Corolla, fatura 3 milyon, 1 milyon finansman.",
    )
    _, s1 = send_message(sid, "Evet, onaylıyorum", idempotency_key="abc")
    _, s2 = send_message(sid, "Evet", idempotency_key="abc")
    assert s1.application_id == s2.application_id


def test_resume_after_close_continues_at_same_step():
    """Simulate the user closing the app mid-flow and coming back."""
    sid = f"resume-{uuid.uuid4().hex[:8]}"
    accept_consent(sid)
    send_message(sid, "İkinci el araç için başvuracağım.")
    # State persisted between turns; loading next turn must NOT reset progress.
    _, s = send_message(sid, "Kasko değeri 2 milyon")
    assert s.fields.casco_value == 2_000_000
    assert s.current_step != ConversationStep.START
