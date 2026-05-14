from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.enums import ApplicationStatus, FinanceType
from app.domain.schemas import ApplicationFields, ConversationStateModel, ValidationResult
from app.domain.tckn import mask_tckn
from app.persistence.database import get_session
from app.persistence.models import (
    AuditLog,
    ConversationStateRow,
    HgsLead,
    IdempotencyRecord,
    LLMUsageLog,
    VehicleFinanceApplication,
)


class ConversationRepository:
    def load(self, session_id: str) -> ConversationStateModel | None:
        with get_session() as s:
            row = s.get(ConversationStateRow, session_id)
            if row is None:
                return None
            try:
                return ConversationStateModel.model_validate(row.state_json)
            except Exception:
                return None

    def save(self, state: ConversationStateModel) -> None:
        state.updated_at = datetime.utcnow()
        with get_session() as s:
            row = s.get(ConversationStateRow, state.session_id)
            payload = state.model_dump(mode="json")
            if row is None:
                row = ConversationStateRow(
                    session_id=state.session_id,
                    customer_id=state.customer_id,
                    state_json=payload,
                )
                s.add(row)
            else:
                row.customer_id = state.customer_id
                row.state_json = payload
            s.commit()


class ApplicationRepository:
    def get(self, application_id: str) -> VehicleFinanceApplication | None:
        with get_session() as s:
            return s.get(VehicleFinanceApplication, application_id)

    def find_by_idempotency(
        self, scope: str, key: str
    ) -> VehicleFinanceApplication | None:
        with get_session() as s:
            rec = s.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope, IdempotencyRecord.key == key
                )
            ).scalar_one_or_none()
            if rec is None:
                return None
            return s.get(VehicleFinanceApplication, rec.target_id)

    def create(
        self,
        *,
        customer_id: str,
        session_id: str,
        finance_type: FinanceType,
        fields: ApplicationFields,
        validation: ValidationResult,
        idempotency_scope: str,
        idempotency_key: str | None,
    ) -> tuple[VehicleFinanceApplication, bool]:
        """Create application with idempotency. Returns (row, created_flag).

        If idempotency_key already exists for the scope, the existing row is
        returned and `created_flag` is False — no duplicate row is written.
        """
        # Fast path: look up existing.
        if idempotency_key:
            existing = self.find_by_idempotency(idempotency_scope, idempotency_key)
            if existing is not None:
                return existing, False

        app_id = f"APP-{uuid.uuid4().hex[:12].upper()}"
        with get_session() as s:
            row = VehicleFinanceApplication(
                application_id=app_id,
                customer_id=customer_id,
                session_id=session_id,
                finance_type=finance_type.value,
                invoice_value=fields.invoice_value,
                casco_value=fields.casco_value,
                vehicle_model=fields.vehicle_model,
                registration_date=fields.registration_date,
                vehicle_age=fields.vehicle_age,
                requested_amount=fields.requested_amount or 0.0,
                guarantor_tckn_masked=mask_tckn(fields.guarantor_tckn),
                seller_tckn_masked=mask_tckn(fields.seller_tckn),
                max_allowed_amount=validation.max_allowed_amount,
                status=ApplicationStatus.PRE_APPLICATION_CREATED.value,
                idempotency_key=idempotency_key,
            )
            s.add(row)
            if idempotency_key:
                s.add(
                    IdempotencyRecord(
                        scope=idempotency_scope,
                        key=idempotency_key,
                        target_id=app_id,
                    )
                )
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                # Another writer beat us — look up and return.
                existing = self.find_by_idempotency(idempotency_scope, idempotency_key or "")
                if existing is not None:
                    return existing, False
                raise
            s.refresh(row)
            return row, True


class HgsRepository:
    def create_lead(
        self, customer_id: str, application_id: str, interest: bool
    ) -> HgsLead:
        with get_session() as s:
            lead = HgsLead(
                customer_id=customer_id,
                related_application_id=application_id,
                interest=interest,
            )
            s.add(lead)
            s.commit()
            s.refresh(lead)
            return lead


class AuditRepository:
    def write(
        self,
        event_type: str,
        *,
        session_id: str | None,
        customer_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with get_session() as s:
            s.add(
                AuditLog(
                    session_id=session_id,
                    customer_id=customer_id,
                    event_type=event_type,
                    payload=payload or {},
                )
            )
            s.commit()


class LLMUsageRepository:
    def write(
        self,
        *,
        session_id: str | None,
        customer_id_hash: str | None,
        conversation_step: str | None,
        node_purpose: str | None,
        model_name: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost_usd: float,
        latency_ms: int,
        litellm_call_id: str | None,
        fallback_used: bool = False,
        trimmed_context_count: int = 0,
    ) -> None:
        with get_session() as s:
            s.add(
                LLMUsageLog(
                    session_id=session_id,
                    customer_id_hash=customer_id_hash,
                    conversation_step=conversation_step,
                    node_purpose=node_purpose,
                    model_name=model_name,
                    provider=provider,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_usd=estimated_cost_usd,
                    latency_ms=latency_ms,
                    litellm_call_id=litellm_call_id,
                    fallback_used=fallback_used,
                    trimmed_context_count=trimmed_context_count,
                )
            )
            s.commit()

    def list_recent(self, limit: int = 100) -> list[LLMUsageLog]:
        with get_session() as s:
            return (
                s.query(LLMUsageLog)
                .order_by(LLMUsageLog.created_at.desc())
                .limit(limit)
                .all()
            )

    def summary(self) -> dict[str, Any]:
        from sqlalchemy import func

        with get_session() as s:
            rows = (
                s.query(
                    LLMUsageLog.model_name,
                    LLMUsageLog.node_purpose,
                    func.count(LLMUsageLog.id),
                    func.sum(LLMUsageLog.prompt_tokens),
                    func.sum(LLMUsageLog.completion_tokens),
                    func.sum(LLMUsageLog.total_tokens),
                    func.sum(LLMUsageLog.estimated_cost_usd),
                    func.avg(LLMUsageLog.latency_ms),
                )
                .group_by(LLMUsageLog.model_name, LLMUsageLog.node_purpose)
                .all()
            )
            buckets = [
                {
                    "model_name": r[0],
                    "node_purpose": r[1],
                    "calls": int(r[2] or 0),
                    "prompt_tokens": int(r[3] or 0),
                    "completion_tokens": int(r[4] or 0),
                    "total_tokens": int(r[5] or 0),
                    "estimated_cost_usd": round(float(r[6] or 0.0), 6),
                    "avg_latency_ms": round(float(r[7] or 0.0), 1),
                }
                for r in rows
            ]
            return {
                "total_calls": sum(b["calls"] for b in buckets),
                "total_tokens": sum(b["total_tokens"] for b in buckets),
                "total_cost_usd": round(sum(b["estimated_cost_usd"] for b in buckets), 6),
                "by_model_and_node": buckets,
            }

    def tokens_used_for_customer(
        self, customer_id_hash: str | None, window_seconds: int
    ) -> int:
        """Customer'ın son ``window_seconds`` içinde tükettiği toplam token.
        Hash sözleşmesi: ``usage_logger.hash_customer`` ile aynı."""
        if not customer_id_hash:
            return 0
        from datetime import timedelta

        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
        with get_session() as s:
            value = (
                s.query(func.coalesce(func.sum(LLMUsageLog.total_tokens), 0))
                .filter(LLMUsageLog.customer_id_hash == customer_id_hash)
                .filter(LLMUsageLog.created_at >= cutoff)
                .scalar()
            )
            return int(value or 0)

    def customer_usage_summary(
        self, customer_id_hash: str | None, *, recent_limit: int = 20
    ) -> dict[str, Any]:
        from datetime import timedelta

        from sqlalchemy import func

        if not customer_id_hash:
            return {"customer_id_hash": None, "total_tokens": 0, "calls": 0, "recent": []}

        now = datetime.utcnow()
        with get_session() as s:
            total = (
                s.query(
                    func.count(LLMUsageLog.id),
                    func.coalesce(func.sum(LLMUsageLog.total_tokens), 0),
                    func.coalesce(func.sum(LLMUsageLog.estimated_cost_usd), 0.0),
                )
                .filter(LLMUsageLog.customer_id_hash == customer_id_hash)
                .one()
            )
            last_1h = (
                s.query(func.coalesce(func.sum(LLMUsageLog.total_tokens), 0))
                .filter(LLMUsageLog.customer_id_hash == customer_id_hash)
                .filter(LLMUsageLog.created_at >= now - timedelta(hours=1))
                .scalar()
            )
            last_24h = (
                s.query(func.coalesce(func.sum(LLMUsageLog.total_tokens), 0))
                .filter(LLMUsageLog.customer_id_hash == customer_id_hash)
                .filter(LLMUsageLog.created_at >= now - timedelta(hours=24))
                .scalar()
            )
            recent = (
                s.query(LLMUsageLog)
                .filter(LLMUsageLog.customer_id_hash == customer_id_hash)
                .order_by(LLMUsageLog.created_at.desc())
                .limit(recent_limit)
                .all()
            )
            return {
                "customer_id_hash": customer_id_hash,
                "calls": int(total[0] or 0),
                "total_tokens": int(total[1] or 0),
                "estimated_cost_usd": round(float(total[2] or 0.0), 6),
                "tokens_last_1h": int(last_1h or 0),
                "tokens_last_24h": int(last_24h or 0),
                "recent": [
                    {
                        "created_at": r.created_at.isoformat() + "Z",
                        "node_purpose": r.node_purpose,
                        "model_name": r.model_name,
                        "total_tokens": r.total_tokens,
                        "estimated_cost_usd": float(r.estimated_cost_usd or 0.0),
                        "fallback_used": r.fallback_used,
                    }
                    for r in recent
                ],
            }
