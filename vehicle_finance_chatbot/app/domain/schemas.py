from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    ActionType,
    ApplicationStatus,
    ConsentStatus,
    ConversationStep,
    FinanceType,
    IntentType,
)


# --- Business constants ---
NEW_VEHICLE_MAX_INVOICE_VALUE: float = 7_000_000.0
NEW_VEHICLE_GUARANTOR_THRESHOLD: float = 5_000_000.0
NEW_VEHICLE_MAX_FINANCING_RATIO: float = 0.60
USED_VEHICLE_MAX_AGE: int = 5
USED_VEHICLE_MAX_FINANCING_RATIO: float = 0.40
USED_VEHICLE_MAX_FINANCING_AMOUNT: float = 3_000_000.0


# --- Auth/session context ---
class CustomerProfile(BaseModel):
    customer_id: str
    full_name: str
    masked_tckn: str
    phone: str
    segment: str = "MASS"
    authenticated: bool = True


# --- Application fields ---
class ApplicationFields(BaseModel):
    finance_type: FinanceType | None = None

    # NEW
    invoice_value: float | None = None
    vehicle_model: str | None = None
    guarantor_tckn: str | None = None

    # USED
    casco_value: float | None = None
    registration_date: date | None = None
    vehicle_age: int | None = None
    model_year: int | None = None
    seller_tckn: str | None = None
    seller_tckn_intent_skipped: bool = False
    approximate_age_requires_confirmation: bool = False

    # Common
    requested_amount: float | None = None


# --- Validation result ---
class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    max_allowed_amount: float | None = None
    requires_guarantor: bool = False


# --- LLM extraction schema ---
class ExtractedFields(BaseModel):
    intent: IntentType = IntentType.UNKNOWN
    finance_type: FinanceType | None = None

    invoice_value: float | None = None
    vehicle_model: str | None = None
    guarantor_tckn: str | None = None

    casco_value: float | None = None
    model_year: int | None = None
    vehicle_age: int | None = None
    registration_date: date | None = None
    seller_tckn: str | None = None
    seller_tckn_skip: bool = False

    requested_amount: float | None = None

    faq_question: str | None = None
    field_to_update: str | None = None
    confidence: float = 0.5


# --- Conversation state ---
class ConversationStateModel(BaseModel):
    session_id: str
    customer_id: str | None = None

    consent_status: ConsentStatus = ConsentStatus.NOT_ASKED
    current_step: ConversationStep = ConversationStep.START
    fields: ApplicationFields = Field(default_factory=ApplicationFields)

    last_validation: ValidationResult | None = None
    pending_question: str | None = None
    pending_application_message: str | None = None  # First-turn message to replay after consent
    application_id: str | None = None
    hgs_offered: bool = False
    hgs_accepted: bool | None = None
    guardrail_triggered: bool = False
    handoff_reason: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- API I/O ---
class ChatRequest(BaseModel):
    session_id: str
    message: str
    idempotency_key: str | None = None


class ChatAction(BaseModel):
    type: ActionType
    field: str | None = None
    payload: dict[str, Any] | None = None


class ChatStateView(BaseModel):
    current_step: ConversationStep
    finance_type: FinanceType | None = None
    consent_status: ConsentStatus
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    application_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    state: ChatStateView
    actions: list[ChatAction] = Field(default_factory=list)


class ApplicationView(BaseModel):
    application_id: str
    customer_id: str
    session_id: str
    finance_type: FinanceType
    status: ApplicationStatus
    invoice_value: float | None
    casco_value: float | None
    vehicle_model: str | None
    registration_date: date | None
    vehicle_age: int | None
    requested_amount: float
    guarantor_tckn_masked: str | None
    seller_tckn_masked: str | None
    max_allowed_amount: float | None
    created_at: datetime
