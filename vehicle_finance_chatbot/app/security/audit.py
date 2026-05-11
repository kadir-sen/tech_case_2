from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.persistence.repositories import AuditRepository
from app.security.pii import mask_payload

_settings = get_settings()
_logger = logging.getLogger("audit")
_logger.setLevel(logging.INFO)

_audit_path = Path(_settings.audit_log_path)
_audit_path.parent.mkdir(parents=True, exist_ok=True)

_handler: logging.Handler | None = None


def _ensure_handler() -> None:
    global _handler
    if _handler is None:
        _handler = logging.FileHandler(_audit_path, encoding="utf-8")
        _handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(_handler)


# Critical events emitted across the chat workflow.
EVENT_CONSENT_ACCEPTED = "consent_accepted"
EVENT_CONSENT_REJECTED = "consent_rejected"
EVENT_FIELD_UPDATED = "field_updated"
EVENT_VALIDATION_PASSED = "validation_passed"
EVENT_VALIDATION_FAILED = "validation_failed"
EVENT_SUMMARY_SHOWN = "summary_shown"
EVENT_APPLICATION_PERSISTED = "application_persisted"
EVENT_HGS_OFFERED = "hgs_offered"
EVENT_HGS_ACCEPTED = "hgs_accepted"
EVENT_HGS_REJECTED = "hgs_rejected"
EVENT_GUARDRAIL_TRIGGERED = "guardrail_triggered"
EVENT_HANDOFF = "handoff"


_repo = AuditRepository()


def audit(
    event_type: str,
    *,
    session_id: str | None = None,
    customer_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    masked = mask_payload(payload or {}) if _settings.pii_log_masking else (payload or {})
    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "session_id": session_id,
        "customer_id": customer_id,
        "payload": masked,
    }
    try:
        _ensure_handler()
        _logger.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass
    try:
        _repo.write(
            event_type,
            session_id=session_id,
            customer_id=customer_id,
            payload=masked,
        )
    except Exception:
        # Audit must never block the request path.
        pass
