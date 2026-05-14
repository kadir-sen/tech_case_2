from datetime import date

from app.domain.enums import FinanceType
from app.domain.rules import validate_used_vehicle_application
from app.domain.schemas import ApplicationFields


def _base(**kw) -> ApplicationFields:
    fields = ApplicationFields(
        finance_type=FinanceType.USED,
        casco_value=2_400_000,
        registration_date=date(2023, 6, 1),
        requested_amount=900_000,
    )
    for k, v in kw.items():
        setattr(fields, k, v)
    return fields


def test_valid_used_application():
    res = validate_used_vehicle_application(_base())
    assert res.is_valid
    assert res.max_allowed_amount == round(2_400_000 * 0.40, 2)


def test_age_over_5_rejected():
    old = _base(registration_date=date(2010, 1, 1))
    res = validate_used_vehicle_application(old)
    assert not res.is_valid
    assert any("5" in e for e in res.errors)


def test_40_percent_cap():
    fields = _base(casco_value=4_000_000, requested_amount=2_000_000)
    res = validate_used_vehicle_application(fields)
    assert not res.is_valid
    # max should be 1.6M
    assert any("1.600.000" in e for e in res.errors)


def test_3m_upper_cap():
    fields = _base(casco_value=10_000_000, requested_amount=4_000_000)
    res = validate_used_vehicle_application(fields)
    assert res.max_allowed_amount == 3_000_000.0
    assert not res.is_valid


def test_seller_tckn_optional_when_blank():
    fields = _base()
    fields.seller_tckn = None
    res = validate_used_vehicle_application(fields)
    assert res.is_valid


def test_model_year_alone_requires_registration_date():
    fields = ApplicationFields(
        finance_type=FinanceType.USED,
        casco_value=2_400_000,
        model_year=2022,
        requested_amount=900_000,
    )
    res = validate_used_vehicle_application(fields)
    assert not res.is_valid
    assert "registration_date" in res.missing_fields
