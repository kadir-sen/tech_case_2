from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.date_utils import compute_vehicle_age
from app.domain.tckn import is_valid_tckn
from app.domain.vehicle_catalog import resolve_vehicle_model
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

    if ex.vehicle_model and (
        not fields.vehicle_model
        or (fields.vehicle_model != ex.vehicle_model and ex.field_to_update == "vehicle_model")
    ):
        resolution = resolve_vehicle_model(ex.vehicle_model)
        if resolution.is_confident and resolution.model is not None:
            fields.vehicle_model = resolution.model.model_name
        else:
            # Düşük güven — kullanıcı ham haliyle yazdığında collection_node
            # disambiguation prompt'u tetikleyebilir. Şu an ham hali saklanır;
            # is_commercial_model fuzzy çözümleme yapar.
            fields.vehicle_model = ex.vehicle_model
            if resolution.confidence > 0:
                graph_state.metadata["vehicle_model_disambiguation"] = {
                    "raw": ex.vehicle_model,
                    "candidate": resolution.model.model_name if resolution.model else None,
                    "confidence": resolution.confidence,
                }
        updated.append("vehicle_model")

    if ex.registration_date is not None:
        fields.registration_date = ex.registration_date
        fields.vehicle_age = compute_vehicle_age(ex.registration_date)
        updated.append("registration_date")
    elif ex.vehicle_age is not None and fields.registration_date is None:
        fields.vehicle_age = ex.vehicle_age
        updated.append("vehicle_age")
    elif ex.model_year is not None and fields.registration_date is None and fields.vehicle_age is None:
        fields.model_year = ex.model_year
        updated.append("model_year")

    if ex.guarantor_tckn:
        if not is_valid_tckn(ex.guarantor_tckn):
            graph_state.metadata["invalid_guarantor_tckn"] = True
        else:
            fields.guarantor_tckn = ex.guarantor_tckn
            updated.append("guarantor_tckn")

    if ex.seller_tckn:
        if is_valid_tckn(ex.seller_tckn):
            fields.seller_tckn = ex.seller_tckn
            updated.append("seller_tckn")
        else:
            graph_state.metadata["invalid_seller_tckn"] = True

    if updated:
        audit(
            EVENT_FIELD_UPDATED,
            session_id=state.session_id,
            customer_id=state.customer_id,
            payload={"updated_fields": updated},
        )

    return graph_state
