from app.domain.enums import FinanceType
from app.domain.rules import validate_new_vehicle_application
from app.domain.schemas import ApplicationFields
from tests.conftest import VALID_TCKN_GUARANTOR


def _base(**kw) -> ApplicationFields:
    fields = ApplicationFields(
        finance_type=FinanceType.NEW,
        vehicle_model="Toyota Corolla",
        invoice_value=4_000_000,
        requested_amount=2_000_000,
    )
    for k, v in kw.items():
        setattr(fields, k, v)
    return fields


def test_valid_under_thresholds():
    res = validate_new_vehicle_application(_base())
    assert res.is_valid
    assert res.max_allowed_amount == 4_000_000 * 0.60


def test_invoice_above_7m_is_rejected():
    res = validate_new_vehicle_application(_base(invoice_value=8_000_000, requested_amount=2_000_000))
    assert not res.is_valid
    assert any("7" in e for e in res.errors)


def test_commercial_model_is_rejected():
    res = validate_new_vehicle_application(_base(vehicle_model="Ford Transit"))
    assert not res.is_valid
    assert any("Ticari" in e or "ticari" in e for e in res.errors)


def test_requested_above_60_percent_is_rejected():
    res = validate_new_vehicle_application(_base(invoice_value=4_000_000, requested_amount=3_000_000))
    assert not res.is_valid
    assert any("maksimum" in e.lower() for e in res.errors)


def test_guarantor_required_above_5m():
    # Without guarantor → missing.
    res = validate_new_vehicle_application(_base(invoice_value=6_000_000, requested_amount=3_000_000))
    assert not res.is_valid
    assert res.requires_guarantor
    assert "guarantor_tckn" in res.missing_fields

    # With valid guarantor → valid.
    res2 = validate_new_vehicle_application(
        _base(
            invoice_value=6_000_000,
            requested_amount=3_000_000,
            guarantor_tckn=VALID_TCKN_GUARANTOR,
        )
    )
    assert res2.is_valid


def test_unknown_model_is_accepted_when_not_commercial():
    # Case sadece ticari/değil ayrımı ister; kataloğa kayıtlı olmayan binek
    # modeller geçerli sayılır.
    res = validate_new_vehicle_application(_base(vehicle_model="Lada Niva"))
    assert res.is_valid
