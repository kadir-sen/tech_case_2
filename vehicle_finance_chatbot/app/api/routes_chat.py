from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.session_context import require_customer
from app.chatbot.graph import run_turn
from app.chatbot.state import GraphState
from app.domain.schemas import (
    ChatRequest,
    ChatResponse,
    ChatStateView,
    ConversationStateModel,
    CustomerProfile,
)
from app.persistence.repositories import ApplicationRepository, ConversationRepository

router = APIRouter()
_conv_repo = ConversationRepository()
_app_repo = ApplicationRepository()


def _state_view(state: ConversationStateModel) -> ChatStateView:
    return ChatStateView(
        current_step=state.current_step,
        finance_type=state.fields.finance_type,
        consent_status=state.consent_status,
        missing_fields=(state.last_validation.missing_fields if state.last_validation else []),
        validation_errors=(state.last_validation.errors if state.last_validation else []),
        application_id=state.application_id,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    customer: CustomerProfile = Depends(require_customer),
) -> ChatResponse:
    state = _conv_repo.load(req.session_id)
    if state is None:
        state = ConversationStateModel(session_id=req.session_id, customer_id=customer.customer_id)
    else:
        # Cross-check: a session must stay tied to the same authenticated customer.
        if state.customer_id and state.customer_id != customer.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session belongs to a different customer.",
            )
        state.customer_id = customer.customer_id

    gs = GraphState(
        user_message=req.message,
        state=state,
        customer=customer,
        idempotency_key=req.idempotency_key,
    )
    run_turn(gs)

    # Append a minimal transcript trail (no PII).
    state.history.append(
        {"role": "user", "text": req.message[:500]}
    )
    state.history.append(
        {"role": "assistant", "text": gs.reply()[:1000]}
    )
    _conv_repo.save(state)

    return ChatResponse(
        session_id=state.session_id,
        reply=gs.reply(),
        state=_state_view(state),
        actions=gs.actions,
    )


@router.get("/sessions/{session_id}")
def get_session(session_id: str, customer: CustomerProfile = Depends(require_customer)):
    state = _conv_repo.load(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if state.customer_id and state.customer_id != customer.customer_id:
        raise HTTPException(status_code=403, detail="Forbidden.")
    return state.model_dump(mode="json")


@router.get("/applications/{application_id}")
def get_application(application_id: str, customer: CustomerProfile = Depends(require_customer)):
    row = _app_repo.get(application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if row.customer_id != customer.customer_id:
        raise HTTPException(status_code=403, detail="Forbidden.")
    return {
        "application_id": row.application_id,
        "customer_id": row.customer_id,
        "session_id": row.session_id,
        "finance_type": row.finance_type,
        "status": row.status,
        "invoice_value": row.invoice_value,
        "casco_value": row.casco_value,
        "vehicle_model": row.vehicle_model,
        "registration_date": row.registration_date.isoformat() if row.registration_date else None,
        "vehicle_age": row.vehicle_age,
        "requested_amount": row.requested_amount,
        "guarantor_tckn_masked": row.guarantor_tckn_masked,
        "seller_tckn_masked": row.seller_tckn_masked,
        "max_allowed_amount": row.max_allowed_amount,
        "created_at": row.created_at.isoformat(),
    }
