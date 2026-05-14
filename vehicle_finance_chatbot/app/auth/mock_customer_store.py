from __future__ import annotations

from app.domain.schemas import CustomerProfile

# Mock customer directory. In production, profile is loaded from the bank's
# customer master/session service after mobile-app authentication. Mask
# values are stored directly; the chatbot never sees a raw TCKN.
#
# ``gender`` alanı customer-master'da her zaman dolu kabul edilir; greeting
# katmanı bu alanı kullanarak "Bey / Hanım" hitabını **LLM olmadan**
# deterministic olarak üretir.
_CUSTOMERS: dict[str, CustomerProfile] = {
    cid: CustomerProfile(
        customer_id=cid,
        full_name=name,
        gender=gender,
        masked_tckn=masked,
        phone=phone,
        segment=segment,
    )
    for cid, name, gender, masked, phone, segment in (
        ("CUST001", "Ayşe Yılmaz", "FEMALE", "600*****492", "+90 555 *** 12 34", "MASS"),
        ("CUST002", "Mehmet Demir", "MALE", "181*****882", "+90 555 *** 56 78", "AFFLUENT"),
        ("CUST003", "Zeynep Kaya", "FEMALE", "358*****272", "+90 555 *** 11 22", "MASS"),
    )
}


def get_customer(customer_id: str | None) -> CustomerProfile | None:
    if not customer_id:
        return None
    return _CUSTOMERS.get(customer_id)
