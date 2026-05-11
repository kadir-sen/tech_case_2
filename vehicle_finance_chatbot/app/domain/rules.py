from __future__ import annotations

from app.domain.date_utils import compute_vehicle_age
from app.domain.schemas import (
    NEW_VEHICLE_GUARANTOR_THRESHOLD,
    NEW_VEHICLE_MAX_FINANCING_RATIO,
    NEW_VEHICLE_MAX_INVOICE_VALUE,
    USED_VEHICLE_MAX_AGE,
    USED_VEHICLE_MAX_FINANCING_AMOUNT,
    USED_VEHICLE_MAX_FINANCING_RATIO,
    ApplicationFields,
    ValidationResult,
)
from app.domain.tckn import is_valid_tckn
from app.domain.vehicle_catalog import is_commercial_model, is_unknown_model


def _fmt(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", ".") + " TL"


def validate_new_vehicle_application(fields: ApplicationFields) -> ValidationResult:
    """Deterministic rule check for NEW vehicle applications. Independent of LLM."""
    errors: list[str] = []
    missing: list[str] = []

    if fields.invoice_value is None:
        missing.append("invoice_value")
    if not fields.vehicle_model:
        missing.append("vehicle_model")
    if fields.requested_amount is None:
        missing.append("requested_amount")

    invoice_value = fields.invoice_value or 0.0
    requested = fields.requested_amount or 0.0
    max_allowed: float | None = None
    requires_guarantor = False

    if invoice_value > NEW_VEHICLE_MAX_INVOICE_VALUE:
        errors.append(
            f"Araç proforma fatura değeri {_fmt(NEW_VEHICLE_MAX_INVOICE_VALUE)} "
            "üzerinde olduğu için yeni taşıt finansmanı başvurusu oluşturulamaz."
        )

    if fields.vehicle_model:
        if is_commercial_model(fields.vehicle_model):
            errors.append("Ticari araç modelleri için yeni taşıt finansmanı başvurusu oluşturulamaz.")
        elif is_unknown_model(fields.vehicle_model):
            # Not an error per se — flagged through missing for clarification.
            missing.append("vehicle_model_clarification")

    if fields.invoice_value is not None:
        max_allowed = round(invoice_value * NEW_VEHICLE_MAX_FINANCING_RATIO, 2)
        if requested > max_allowed:
            errors.append(
                f"Talep edilebilecek maksimum finansman tutarı {_fmt(max_allowed)} olabilir. "
                f"Talep ettiğiniz {_fmt(requested)} bu limiti aşıyor."
            )

    if fields.invoice_value is not None and invoice_value >= NEW_VEHICLE_GUARANTOR_THRESHOLD:
        requires_guarantor = True
        if not fields.guarantor_tckn:
            missing.append("guarantor_tckn")
        elif not is_valid_tckn(fields.guarantor_tckn):
            errors.append("Kefil TCKN bilgisi geçersiz.")

    is_valid = len(errors) == 0 and len(missing) == 0
    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        missing_fields=missing,
        max_allowed_amount=max_allowed,
        requires_guarantor=requires_guarantor,
    )


def validate_used_vehicle_application(fields: ApplicationFields) -> ValidationResult:
    """Deterministic rule check for USED vehicle applications."""
    errors: list[str] = []
    missing: list[str] = []

    if fields.casco_value is None:
        missing.append("casco_value")
    if fields.requested_amount is None:
        missing.append("requested_amount")

    # Vehicle age handling — prefer registration_date, then explicit age, then model_year
    age: int | None = None
    if fields.registration_date is not None:
        age = compute_vehicle_age(fields.registration_date)
    elif fields.vehicle_age is not None:
        age = fields.vehicle_age
    elif fields.model_year is not None:
        # Model year alone is not authoritative; require clarification.
        missing.append("registration_date")
    else:
        missing.append("registration_date")

    if age is not None and age > USED_VEHICLE_MAX_AGE:
        errors.append(
            f"{USED_VEHICLE_MAX_AGE} yaş üstü araçlar için ikinci el taşıt finansmanı başvurusu oluşturulamaz."
        )

    max_allowed: float | None = None
    if fields.casco_value is not None:
        max_allowed = round(
            min(fields.casco_value * USED_VEHICLE_MAX_FINANCING_RATIO, USED_VEHICLE_MAX_FINANCING_AMOUNT),
            2,
        )
        if fields.requested_amount is not None and fields.requested_amount > max_allowed:
            errors.append(
                f"Talep edilebilecek maksimum finansman tutarı {_fmt(max_allowed)} olabilir. "
                f"Talep ettiğiniz {_fmt(fields.requested_amount)} bu limiti aşıyor."
            )

    if fields.seller_tckn and not is_valid_tckn(fields.seller_tckn):
        errors.append("Satıcı TCKN bilgisi geçersiz.")

    is_valid = len(errors) == 0 and len(missing) == 0
    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        missing_fields=missing,
        max_allowed_amount=max_allowed,
        requires_guarantor=False,
    )
