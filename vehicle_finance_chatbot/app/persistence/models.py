from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


class CustomerSession(Base):
    __tablename__ = "customer_sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConversationStateRow(Base):
    __tablename__ = "conversation_states"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class VehicleFinanceApplication(Base):
    __tablename__ = "vehicle_finance_applications"

    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    finance_type: Mapped[str] = mapped_column(String)

    invoice_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    casco_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String, nullable=True)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vehicle_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_amount: Mapped[float] = mapped_column(Float)

    # Stored masked for MVP; encryption interface stubbed in security/pii.py.
    guarantor_tckn_masked: Mapped[str | None] = mapped_column(String, nullable=True)
    seller_tckn_masked: Mapped[str | None] = mapped_column(String, nullable=True)

    max_allowed_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="ux_idempotency_scope_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HgsLead(Base):
    __tablename__ = "hgs_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    related_application_id: Mapped[str] = mapped_column(String, index=True)
    interest: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LLMUsageLog(Base):
    """Per-LLM-call usage record. Customer ID is stored as a hash; raw
    prompt/completion text is never stored here — only token counts and
    metadata. This keeps the usage table PII-free and safe to ship to
    cost dashboards.
    """

    __tablename__ = "llm_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    customer_id_hash: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    conversation_step: Mapped[str | None] = mapped_column(String, nullable=True)
    node_purpose: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    model_name: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    litellm_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    trimmed_context_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
