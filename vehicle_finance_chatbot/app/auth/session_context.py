from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.auth.mock_customer_store import get_customer
from app.domain.schemas import CustomerProfile


def require_customer(
    x_customer_id: str | None = Header(default=None, alias="X-Customer-Id"),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> CustomerProfile:
    """Mock authentication: in mobile banking the customer is already logged
    in. We trust the `X-Customer-Id` header coming from the BFF, but require
    the customer to exist in the mock store.
    """
    profile = get_customer(x_customer_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated customer context missing or unknown.",
        )
    return profile
