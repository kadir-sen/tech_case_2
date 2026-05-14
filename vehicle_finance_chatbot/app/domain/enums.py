from __future__ import annotations

from enum import Enum


class FinanceType(str, Enum):
    NEW = "NEW"
    USED = "USED"


class ConversationStep(str, Enum):
    START = "START"
    GREETED = "GREETED"
    AWAITING_INTENT = "AWAITING_INTENT"
    AWAITING_FINANCE_TYPE = "AWAITING_FINANCE_TYPE"
    COLLECTING_FIELDS = "COLLECTING_FIELDS"
    VALIDATING = "VALIDATING"
    AWAITING_FIELD_FIX = "AWAITING_FIELD_FIX"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PERSISTED = "PERSISTED"
    AWAITING_HGS_DECISION = "AWAITING_HGS_DECISION"
    COMPLETED = "COMPLETED"
    HANDOFF = "HANDOFF"


class IntentType(str, Enum):
    GREET = "greet"
    START_APPLICATION = "start_application"
    PROVIDE_INFO = "provide_info"
    UPDATE_FIELD = "update_field"
    CONFIRM = "confirm"
    REJECT = "reject"
    CANCEL = "cancel"
    FAQ_QUESTION = "faq_question"
    HGS_DECISION = "hgs_decision"
    UNDECIDED = "undecided"
    UNKNOWN = "unknown"


class ApplicationStatus(str, Enum):
    PRE_APPLICATION_CREATED = "PRE_APPLICATION_CREATED"
    REJECTED = "REJECTED"


class VehicleClass(str, Enum):
    PASSENGER = "PASSENGER"
    COMMERCIAL = "COMMERCIAL"


class ActionType(str, Enum):
    SHOW_GREETING = "SHOW_GREETING"
    ASK_FINANCE_TYPE = "ASK_FINANCE_TYPE"
    ASK_FIELD = "ASK_FIELD"
    FIX_FIELD = "FIX_FIELD"
    SHOW_SUMMARY = "SHOW_SUMMARY"
    CONFIRM = "CONFIRM"
    OFFER_HGS = "OFFER_HGS"
    HANDOFF = "HANDOFF"
    SAFE_REPLY = "SAFE_REPLY"
    REJECT_APPLICATION = "REJECT_APPLICATION"
    FAQ_ANSWER = "FAQ_ANSWER"
    NONE = "NONE"
