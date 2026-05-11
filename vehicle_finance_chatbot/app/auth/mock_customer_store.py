from __future__ import annotations

from app.domain.schemas import CustomerProfile


# Mock customer directory. In production, profile is loaded from the bank's
# customer master/session service after mobile-app authentication.
_CUSTOMERS: dict[str, CustomerProfile] = {
    "CUST001": CustomerProfile(
        customer_id="CUST001",
        full_name="Ayşe Yılmaz",
        masked_tckn="123******10",
        phone="+90 555 *** 12 34",
        segment="MASS",
    ),
    "CUST002": CustomerProfile(
        customer_id="CUST002",
        full_name="Mehmet Demir",
        masked_tckn="456******02",
        phone="+90 555 *** 56 78",
        segment="AFFLUENT",
    ),
    "CUST003": CustomerProfile(
        customer_id="CUST003",
        full_name="Zeynep Kaya",
        masked_tckn="789******45",
        phone="+90 555 *** 11 22",
        segment="MASS",
    ),
}


def get_customer(customer_id: str | None) -> CustomerProfile | None:
    if not customer_id:
        return None
    return _CUSTOMERS.get(customer_id)
