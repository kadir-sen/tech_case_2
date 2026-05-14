"""ChatRequest.edited_fields → backend merge + revalidate testleri."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_edited_fields_lowering_amount_passes_validation(client):
    sid = _sid("edit-amount")
    # Önce limit aşan başvuru gönder — fix prompt'a düş.
    r1 = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "Yeni araç. Toyota Corolla, fatura 4 milyon, 3 milyon finansman istiyorum.",
        },
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["state"]["current_step"] == "AWAITING_FIELD_FIX"

    # Sonra inline edit ile tutarı düşür + onayla.
    r2 = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "confirm",
            "edited_fields": {"requested_amount": 2_000_000},
        },
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    # Edit + re-validate sonrası özet veya doğrudan persistance.
    assert body["state"]["current_step"] in ("AWAITING_CONFIRMATION", "AWAITING_HGS_DECISION", "PERSISTED")


def test_edited_fields_rejected_when_still_over_limit(client):
    sid = _sid("edit-over")
    r1 = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "Yeni araç. Toyota Corolla, fatura 4 milyon, 3 milyon finansman istiyorum.",
        },
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r1.status_code == 200

    # Edited amount hâlâ %60 üstü — yeniden fix prompt'a düşmeli.
    r2 = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "tutarı güncelliyorum",
            "edited_fields": {"requested_amount": 2_800_000},
        },
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["state"]["current_step"] == "AWAITING_FIELD_FIX"


def test_summary_payload_has_editable_rows(client):
    sid = _sid("edit-summary")
    r = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "Yeni araç. Toyota Corolla, fatura 3 milyon, 1 milyon finansman istiyorum.",
        },
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r.status_code == 200
    body = r.json()
    summary_actions = [a for a in body["actions"] if a["type"] == "SHOW_SUMMARY"]
    assert len(summary_actions) == 1
    payload = summary_actions[0]["payload"]
    keys = {row["key"] for row in payload["fields"]}
    assert {"invoice_value", "requested_amount", "vehicle_model"}.issubset(keys)
    requested = next(r for r in payload["fields"] if r["key"] == "requested_amount")
    assert requested["editable"] is True


def test_init_session_endpoint_returns_greeting(client):
    r = client.post(
        "/chat/session",
        headers={"X-Customer-Id": "CUST001"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "taşıt finansmanı" in body["reply"].lower()
    assert body["state"]["current_step"] == "GREETED"
    types = [a["type"] for a in body["actions"]]
    assert "SHOW_GREETING" in types
