"""Field/intent extraction.

Two implementations:
- ``LLMExtractor``: LangChain ChatOpenAI with structured Pydantic output.
- ``RuleBasedExtractor``: deterministic regex/heuristic extractor that the
  whole system can run on when no LLM is configured (LLM_PROVIDER=mock).

Both implement the same ``extract(message, state)`` interface.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.config import get_settings


def _tr_lower(text: str) -> str:
    """Aggressive Turkish folding for trigger matching.

    Folds: İ/I/ı → i, then lowercases, then strips combining marks (so ç→c,
    ş→s, ğ→g, ö→o, ü→u). This is intentionally lossy — users typing
    "nasil" should match a trigger written as "nasıl". Use only for
    substring keyword detection, never for echo back to the user.
    """
    out = (
        text.replace("İ", "i")
        .replace("I", "i")
        .replace("ı", "i")
        .lower()
    )
    return "".join(c for c in unicodedata.normalize("NFD", out) if not unicodedata.combining(c))


def _norm_tokens(words: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_tr_lower(w) for w in words)
from app.domain.date_utils import parse_date, parse_model_year
from app.domain.enums import ConsentStatus, ConversationStep, FinanceType, IntentType
from app.domain.money import parse_amount
from app.domain.schemas import (
    ConversationStateModel,
    ExtractedFields,
)
from app.chatbot.prompts import SYSTEM_INTENT_EXTRACTION


# --- Heuristics for the rule-based extractor ---

_AFFIRM_WORDS = _norm_tokens(
    (
        "evet",
        "onayl",
        "tamam",
        "olur",
        "kabul",
        "kabul ediyorum",
        "başvuruyu oluştur",
        "yes",
        "confirm",
    )
)
_REJECT_WORDS = _norm_tokens(("hayır", "iptal", "vazgeç", "reddet", "no", "cancel"))
_CONSENT_REJECT_WORDS = _norm_tokens(
    (
        "kvkk istemiyorum",
        "rıza vermiyorum",
        "onay vermiyorum",
        "reddediyorum",
    )
)

_NEW_TOKENS = _norm_tokens(("yeni", "sıfır", "0 km", "sifir", "0km"))
_USED_TOKENS = _norm_tokens(
    ("ikinci el", "2. el", "2.el", "2el", "ikinciel", "kullanılmış", "ikinciel")
)

_RESTART_TOKENS = _norm_tokens(("aslında", "yok aslında", "yok, "))

_FAQ_TRIGGERS = _norm_tokens(
    (
        "nedir",
        "ne kadar",
        "kaç",
        "nasıl",
        "hangi",
        "neden",
        "limit",
        "oran",
        "faiz",
        "yaş sınır",
        "kefil ne zaman",
        "ne zaman gerek",
        "açıklar mısın",
        "anlatır mısın",
        "açıkla",
    )
)

_TCKN_RE = re.compile(r"(?<!\d)([1-9]\d{10})(?!\d)")
_MODEL_AGE_RE = re.compile(r"(\d{1,2})\s*(?:yaşında|yas[ıi]nda|yasinda)")
_FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice_value": ("fatura", "proforma", "arac fiyat", "arac deger"),
    "casco_value": ("kasko",),
    "requested_amount": ("finansman", "kredi", "talep", "istiyorum"),
    "vehicle_age": ("yasinda", "yas"),
    "vehicle_model": ("model",),
    "guarantor_tckn": ("kefil",),
    "seller_tckn": ("satici",),
}


def _detect_finance_type(text: str) -> FinanceType | None:
    lower = _tr_lower(text)
    # Note: the catalog name "iveco daily" contains "daily" but is not
    # itself a finance_type indicator; the check is on Turkish noun tokens.
    if any(t in lower for t in _USED_TOKENS):
        return FinanceType.USED
    if any(t in lower for t in _NEW_TOKENS):
        return FinanceType.NEW
    return None


def _is_faq_question(text: str) -> bool:
    lower = _tr_lower(text)
    return "?" in text or any(t in lower for t in _FAQ_TRIGGERS)


def _extract_amounts(text: str) -> list[float]:
    """Pull up to two distinct amounts. Used to populate value+requested
    when the user gives both in one message ('aracın değeri 4 milyon, 2 milyon istiyorum').
    """
    amounts: list[float] = []
    for match in re.finditer(
        r"(\d+(?:[\.,]\d+)?\s*milyon(?:\s*\d+(?:[\.,]\d+)?\s*bin)?|\d+(?:[\.,]\d+)?\s*bin|\d{1,3}(?:[\.\s]\d{3})+(?:,\d+)?|\d{4,})",
        text,
    ):
        val = parse_amount(match.group(0))
        if val is None:
            continue
        if not any(abs(val - existing) < 1 for existing in amounts):
            amounts.append(val)
    return amounts


def _split_amounts_into_fields(
    text: str, amounts: list[float], finance_type: FinanceType | None
) -> dict[str, float]:
    """Heuristic mapping of multiple amounts in a single message to fields.

    Strategy: find the keyword nearest to each amount in the text. If a
    keyword is not present, fall back to ordered defaults per finance_type.
    """
    out: dict[str, float] = {}
    lower = _tr_lower(text)

    # Try keyword-anchored.
    spans = []
    for match in re.finditer(
        r"(\d+(?:[\.,]\d+)?\s*milyon(?:\s*\d+(?:[\.,]\d+)?\s*bin)?|\d+(?:[\.,]\d+)?\s*bin|\d{1,3}(?:[\.\s]\d{3})+(?:,\d+)?|\d{4,})",
        text,
    ):
        val = parse_amount(match.group(0))
        if val is None:
            continue
        spans.append((match.start(), match.end(), val))

    used_amounts: set[int] = set()
    for span_idx, (start, end, val) in enumerate(spans):
        # Find the closest keyword window in either direction (40 chars).
        window = _tr_lower(text[max(0, start - 40) : min(len(text), end + 20)])
        for field, kws in _FIELD_KEYWORDS.items():
            if field in ("vehicle_age", "vehicle_model", "guarantor_tckn", "seller_tckn"):
                continue
            if any(kw in window for kw in kws):
                # Map by finance type.
                if field == "invoice_value" and finance_type == FinanceType.USED:
                    field = "casco_value"
                if field == "casco_value" and finance_type == FinanceType.NEW:
                    field = "invoice_value"
                if field not in out:
                    out[field] = val
                    used_amounts.add(span_idx)
                    break

    # Fill remaining amounts in order, by finance_type defaults.
    remaining = [val for idx, (_, _, val) in enumerate(spans) if idx not in used_amounts]
    if remaining:
        defaults = (
            ["casco_value", "requested_amount"]
            if finance_type == FinanceType.USED
            else ["invoice_value", "requested_amount"]
        )
        for field in defaults:
            if field not in out and remaining:
                out[field] = remaining.pop(0)

    return out


def _detect_update_request(text: str) -> tuple[str | None, float | None]:
    """If the user is asking to change a single field, return (field, new_value)."""
    lower = _tr_lower(text)
    field: str | None = None
    if "tutar" in lower or "finansman" in lower or "kredi" in lower or "talep" in lower or "istiyorum" in lower:
        field = "requested_amount"
    elif "kasko" in lower:
        field = "casco_value"
    elif "fatura" in lower or "arac deger" in lower:
        field = "invoice_value"
    elif "yas" in lower or "yasinda" in lower:
        field = "vehicle_age"
    elif "model" in lower and "yil" not in lower:
        field = "vehicle_model"
    elif "kefil" in lower:
        field = "guarantor_tckn"
    elif "satici" in lower:
        field = "seller_tckn"

    if field is None:
        return None, None
    amounts = _extract_amounts(text)
    if amounts:
        return field, amounts[0]
    return field, None


class RuleBasedExtractor:
    """Deterministic extractor used in mock mode and as a safety net."""

    def extract(self, message: str, state: ConversationStateModel) -> ExtractedFields:
        text = message.strip()
        lower = _tr_lower(text)
        out = ExtractedFields()

        # --- Consent shortcuts ---
        if state.current_step == ConversationStep.AWAITING_CONSENT or state.consent_status == ConsentStatus.NOT_ASKED:
            if any(w in lower for w in _CONSENT_REJECT_WORDS):
                out.intent = IntentType.REJECT
                out.confidence = 0.95
                return out
            if any(w in lower for w in _REJECT_WORDS) and not any(w in lower for w in _AFFIRM_WORDS):
                out.intent = IntentType.REJECT
                out.confidence = 0.8
                return out
            if any(w in lower for w in _AFFIRM_WORDS):
                out.intent = IntentType.CONFIRM
                out.confidence = 0.95
                return out

        # --- FAQ detection ---
        # A message ending with "?" OR containing a strong FAQ trigger phrase
        # is an FAQ even when it mentions "yeni / ikinci el". Without this,
        # questions like "ikinci el araçta max ne kadar?" would be treated
        # as application starts.
        if "?" in text or any(t in lower for t in _FAQ_TRIGGERS):
            out.intent = IntentType.FAQ_QUESTION
            out.faq_question = text
            out.confidence = 0.85
            return out

        # --- Finance type ---
        ft = _detect_finance_type(text)
        if ft:
            out.finance_type = ft

        # --- Confirmation while awaiting confirmation ---
        if state.current_step == ConversationStep.AWAITING_CONFIRMATION:
            mentions_new = any(t in lower for t in _NEW_TOKENS)
            mentions_used = any(t in lower for t in _USED_TOKENS)
            is_restart = (
                any(t in lower for t in _RESTART_TOKENS)
                or mentions_new
                or mentions_used
            )
            multi_amounts = len(_extract_amounts(text)) > 1
            has_date = bool(re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}", text))

            # Only short-circuit for atomic single-field corrections.
            # Multi-field updates / finance-type switches / restarts fall
            # through to full extraction below.
            if not is_restart and not multi_amounts and not has_date:
                field, new_val = _detect_update_request(text)
                if field:
                    out.intent = IntentType.UPDATE_FIELD
                    out.field_to_update = field
                    if new_val is not None:
                        _apply_field_value(out, field, new_val)
                    out.confidence = 0.85
                    return out
                if any(w in lower for w in _AFFIRM_WORDS):
                    out.intent = IntentType.CONFIRM
                    out.confidence = 0.95
                    return out
                if any(w in lower for w in _REJECT_WORDS):
                    out.intent = IntentType.REJECT
                    out.confidence = 0.9
                    return out
            # Restart/multi-field path → re-extraction
            if is_restart:
                out.intent = IntentType.UPDATE_FIELD

        # --- HGS decision ---
        if state.current_step == ConversationStep.AWAITING_HGS_DECISION:
            if any(w in lower for w in _AFFIRM_WORDS):
                out.intent = IntentType.HGS_DECISION
                out.field_to_update = "hgs_accepted_yes"
                out.confidence = 0.9
                return out
            if any(w in lower for w in _REJECT_WORDS):
                out.intent = IntentType.HGS_DECISION
                out.field_to_update = "hgs_accepted_no"
                out.confidence = 0.9
                return out

        # --- Direct field update during collection ---
        update_only = False
        if state.current_step in (
            ConversationStep.COLLECTING_FIELDS,
            ConversationStep.AWAITING_FIELD_FIX,
        ):
            field, new_val = _detect_update_request(text)
            if field and new_val is not None:
                out.intent = IntentType.UPDATE_FIELD
                out.field_to_update = field
                _apply_field_value(out, field, new_val)
                out.confidence = 0.85
                # Short message asking for a single update — don't reinterpret
                # the same number as another field.
                if len(_extract_amounts(text)) <= 1:
                    update_only = True

        # --- Field extraction ---
        # Always strip TCKN candidates and date spans from the text before
        # running amount detection so they cannot be misread as numbers.
        text_for_amounts = text
        tckn_matches = _TCKN_RE.findall(text)
        if tckn_matches:
            for tk in tckn_matches:
                text_for_amounts = text_for_amounts.replace(tk, " ")
            if "kefil" in lower:
                out.guarantor_tckn = tckn_matches[0]
            elif "satıcı" in lower or "satici" in lower:
                out.seller_tckn = tckn_matches[0]
            else:
                # Default by current step / finance type.
                if state.fields.finance_type == FinanceType.NEW:
                    out.guarantor_tckn = tckn_matches[0]
                elif state.fields.finance_type == FinanceType.USED:
                    out.seller_tckn = tckn_matches[0]

        # "Satıcı TCKN sonra verebilirim" / "satıcı yok"
        if ("sonra" in lower and ("satıcı" in lower or "satici" in lower)) or (
            ("satıcı" in lower or "satici" in lower) and "bilmiyorum" in lower
        ) or ("satıcı tckn" in lower and "yok" in lower):
            out.seller_tckn_skip = True

        # Registration date — also strip the matched span so it isn't
        # later interpreted as an amount.
        reg_date_match = re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}", text)
        reg_date = parse_date(text)
        if reg_date is not None:
            out.registration_date = reg_date
        if reg_date_match:
            text_for_amounts = text_for_amounts.replace(reg_date_match.group(0), " ")

        # Vehicle age
        m = _MODEL_AGE_RE.search(lower)
        if m:
            out.vehicle_age = int(m.group(1))

        # Model year (yyyy) — only if not parsed as date already.
        if out.registration_date is None and out.vehicle_age is None:
            year = parse_model_year(text)
            if year is not None and 1990 <= year <= 2100:
                out.model_year = year

        # Vehicle model
        model = _extract_model_name(text)
        if model:
            out.vehicle_model = model

        # Amounts (invoice/casco/requested)
        if not update_only:
            amounts = _extract_amounts(text_for_amounts)
            if amounts:
                ft_local = out.finance_type or state.fields.finance_type
                mapping = _split_amounts_into_fields(text_for_amounts, amounts, ft_local)
                for k, v in mapping.items():
                    if getattr(out, k, None) is None:
                        setattr(out, k, v)

        # --- Intent fallback ---
        if out.intent == IntentType.UNKNOWN:
            if out.finance_type or any(
                v is not None
                for v in (
                    out.invoice_value,
                    out.casco_value,
                    out.requested_amount,
                    out.vehicle_model,
                    out.vehicle_age,
                    out.registration_date,
                    out.guarantor_tckn,
                    out.seller_tckn,
                )
            ):
                if state.current_step in (
                    ConversationStep.START,
                    ConversationStep.AWAITING_INTENT,
                    ConversationStep.AWAITING_FINANCE_TYPE,
                ):
                    out.intent = IntentType.START_APPLICATION
                else:
                    out.intent = IntentType.PROVIDE_INFO
                out.confidence = 0.8
            elif "başvuru" in lower or "taşıt" in lower or "araç" in lower or "arac" in lower or "kredi" in lower:
                out.intent = IntentType.START_APPLICATION
                out.confidence = 0.7

        return out


def _apply_field_value(out: ExtractedFields, field: str, val: float) -> None:
    if field == "requested_amount":
        out.requested_amount = val
    elif field == "casco_value":
        out.casco_value = val
    elif field == "invoice_value":
        out.invoice_value = val
    elif field == "vehicle_age":
        out.vehicle_age = int(val)


_MODEL_RE = re.compile(
    r"(fiat\s+egea|fiat\s+doblo|renault\s+clio|renault\s+megane|renault\s+kangoo|"
    r"toyota\s+corolla|volkswagen\s+polo|vw\s+polo|volkswagen\s+passat|vw\s+passat|"
    r"vw\s+crafter|volkswagen\s+crafter|bmw\s*3|mercedes\s+c[- ]?class|mercedes\s+sprinter|"
    r"tesla\s+model\s*3|togg\s+t10x|ford\s+transit(\s+custom)?|iveco\s+daily)",
    re.IGNORECASE,
)


def _extract_model_name(text: str) -> str | None:
    m = _MODEL_RE.search(text)
    if m:
        return m.group(0).strip()
    return None


class LLMExtractor:
    """LangChain-based structured extractor with gateway routing.

    When ``LLM_GATEWAY_ENABLED=true`` the call goes through the
    LLMGatewayClient — picking up node-level token budgets, routing,
    fallback and usage logging. Otherwise we keep the legacy direct
    ChatOpenAI path so existing deployments are unaffected.

    Always falls back to ``RuleBasedExtractor`` on errors so a flaky
    local LLM never breaks the chat path.
    """

    def __init__(self) -> None:
        from langchain_openai import ChatOpenAI

        settings = get_settings()
        self._settings = settings
        self._fallback = RuleBasedExtractor()
        # Legacy direct-to-provider path (only used when gateway disabled).
        self._llm = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
        )
        self._structured = self._llm.with_structured_output(ExtractedFields)

    def extract(self, message: str, state: ConversationStateModel) -> ExtractedFields:
        from langchain_core.messages import HumanMessage, SystemMessage

        ctx: dict[str, Any] = {
            "current_step": state.current_step.value,
            "finance_type": state.fields.finance_type.value if state.fields.finance_type else None,
        }

        if self._settings.llm_gateway_enabled:
            try:
                from app.llm_gateway import (
                    BudgetExceededError,
                    get_gateway_client,
                )
                from app.llm_gateway.routing_policy import NODE_FIELD

                client = get_gateway_client()
                response = client.invoke(
                    node_purpose=NODE_FIELD,
                    system_prompt=SYSTEM_INTENT_EXTRACTION,
                    user_message=f"context: {ctx}\nuser: {message}",
                    session_id=state.session_id,
                    customer_id=state.customer_id,
                    conversation_step=state.current_step.value,
                )
                # Gateway path returns plain content; we parse it as JSON
                # into ExtractedFields. If the local model didn't return
                # valid JSON, fall back to rule-based.
                import json

                try:
                    return ExtractedFields.model_validate(json.loads(response.content))
                except Exception:
                    return self._fallback.extract(message, state)
            except BudgetExceededError:
                # Hard safety: never make an unbounded call.
                return self._fallback.extract(message, state)
            except Exception:
                return self._fallback.extract(message, state)

        try:
            result = self._structured.invoke(
                [
                    SystemMessage(content=SYSTEM_INTENT_EXTRACTION),
                    HumanMessage(content=f"context: {ctx}\nuser: {message}"),
                ]
            )
            if isinstance(result, ExtractedFields):
                return result
            return ExtractedFields.model_validate(result)
        except Exception:
            return self._fallback.extract(message, state)


def get_extractor():
    settings = get_settings()
    if settings.llm_provider == "mock" and not settings.llm_gateway_enabled:
        return RuleBasedExtractor()
    try:
        return LLMExtractor()
    except Exception:
        return RuleBasedExtractor()
