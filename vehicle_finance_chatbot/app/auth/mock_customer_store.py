from __future__ import annotations

from app.domain.schemas import CustomerProfile
from app.domain.tckn import mask_tckn

# Mock customer directory. In production, profile is loaded from the bank's
# customer master/session service after mobile-app authentication.
# `_REAL_TCKN_INDEX` represents the bank's encrypted store; it is NEVER
# returned to the client. We use it server-side only — for example to
# detect when a user enters their own TCKN as guarantor.
_REAL_TCKN_INDEX: dict[str, str] = {
    "CUST001": "60064805492",
    "CUST002": "18157176882",
    "CUST003": "35886454272",
}

_CUSTOMERS: dict[str, CustomerProfile] = {
    cid: CustomerProfile(
        customer_id=cid,
        full_name=name,
        masked_tckn=mask_tckn(_REAL_TCKN_INDEX[cid]) or "***",
        phone=phone,
        segment=segment,
    )
    for cid, name, phone, segment in (
        ("CUST001", "Ayşe Yılmaz", "+90 555 *** 12 34", "MASS"),
        ("CUST002", "Mehmet Demir", "+90 555 *** 56 78", "AFFLUENT"),
        ("CUST003", "Zeynep Kaya", "+90 555 *** 11 22", "MASS"),
    )
}


def get_customer(customer_id: str | None) -> CustomerProfile | None:
    if not customer_id:
        return None
    return _CUSTOMERS.get(customer_id)


def get_customer_tckn(customer_id: str | None) -> str | None:
    """Server-internal lookup. Never expose to the client."""
    if not customer_id:
        return None
    return _REAL_TCKN_INDEX.get(customer_id)
