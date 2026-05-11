from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.date_utils import compute_vehicle_age
from app.domain.enums import FinanceType
from app.domain.tckn import is_valid_tckn
from app.security.audit import EVENT_FIELD_UPDATED, audit


def field_extraction_node(graph_state: GraphState) -> GraphState:
    """Merge extracted fields into the persisted state.

    Notes:
    - registration_date overrides vehicle_age (registration is authoritative).
    - guarantor/seller TCKN are only stored if they pass checksum validation.
    - finance_type may be set on this turn; downstream nodes branch on it.
    """
    if graph_state.extracted is None:
        return graph_state

    ex = graph_state.extracted
    state = graph_state.state
    fields = state.fields
    updated: list[str] = []

    if ex.finance_type and fields.finance_type != ex.finance_type:
        fields.finance_type = ex.finance_type
        updated.append("finance_type")

    if ex.invoice_value is not None and ex.invoice_value > 0:
        if fields.invoice_value != ex.invoice_value:
            fields.invoice_value = ex.invoice_value
            updated.append("invoice_value")

    if ex.casco_value is not None and ex.casco_value > 0:
        if fields.casco_value != ex.casco_value:
            fields.casco_value = ex.casco_value
            updated.append("casco_value")

    if ex.requested_amount is not None and ex.requested_amount > 0:
        if fields.requested_amount != ex.requested_amount:
            fields.requested_amount = ex.requested_amount
            updated.append("requested_amount")

    if ex.vehicle_model and not fields.vehicle_model:
        fields.vehicle_model = ex.vehicle_model
        updated.append("vehicle_model")
    elif ex.vehicle_model and fields.vehicle_model != ex.vehicle_model and ex.field_to_update == "vehicle_model":
        fields.vehicle_model = ex.vehicle_model
        updated.append("vehicle_model")

    if ex.registration_date is not None:
        fields.registration_date = ex.registration_date
        fields.vehicle_age = compute_vehicle_age(ex.registration_date)
        fields.approximate_age_requires_confirmation = False
        updated.append("registration_date")
    elif ex.vehicle_age is not None and fields.registration_date is None:
        fields.vehicle_age = ex.vehicle_age
        fields.approximate_age_requires_confirmation = True
        updated.append("vehicle_age")
    elif ex.model_year is not None and fields.registration_date is None and fields.vehicle_age is None:
        fields.model_year = ex.model_year
        fields.approximate_age_requires_confirmation = True
        updated.append("model_year")

    if ex.guarantor_tckn:
        if is_valid_tckn(ex.guarantor_tckn):
            fields.guarantor_tckn = ex.guarantor_tckn
            updated.append("guarantor_tckn")
        else:
            graph_state.metadata["invalid_guarantor_tckn"] = True

    if ex.seller_tckn:
        if is_valid_tckn(ex.seller_tckn):
            fields.seller_tckn = ex.seller_tckn
            updated.append("seller_tckn")
        else:
            graph_state.metadata["invalid_seller_tckn"] = True

    if ex.seller_tckn_skip and fields.finance_type == FinanceType.USED:
        fields.seller_tckn_intent_skipped = True
        updated.append("seller_tckn_skipped")

    if updated:
        audit(
            EVENT_FIELD_UPDATED,
            session_id=state.session_id,
            customer_id=state.customer_id,
            payload={"updated_fields": updated},
        )

    return graph_state
