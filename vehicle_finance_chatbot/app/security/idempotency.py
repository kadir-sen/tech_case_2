from __future__ import annotations

# Scope strings used with IdempotencyRecord. Centralised so persistence and
# the chat layer agree on identifiers.

SCOPE_APPLICATION_CREATE = "application_create"
SCOPE_HGS_LEAD = "hgs_lead"


def build_application_key(session_id: str, idempotency_key: str | None) -> str:
    """For application creation we use the session's confirmation as the
    natural idempotency key when the client did not provide one. This makes
    "second click on confirm" safe even without an explicit key.
    """
    if idempotency_key:
        return f"{session_id}:{idempotency_key}"
    return f"{session_id}:confirm"
