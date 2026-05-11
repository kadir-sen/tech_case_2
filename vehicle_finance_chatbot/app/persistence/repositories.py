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
