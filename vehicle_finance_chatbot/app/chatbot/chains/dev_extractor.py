"""Deterministic LLM extractor stub — yalnızca testler ve demo için.

Production yolu (``LLMExtractor``) gerçek LLM çağırır. Bu modül CI ortamında
ve ``scripts/demo_conversation.py`` içinde gerçek bir LLM ayağa kaldırmadan
end-to-end akış doğrulanabilsin diye var. Production import path'inde
ÇAĞRILMAZ — sadece testler ve demo scripti monkey-patch eder.

Anahtar kelime sözlüğüyle çalışır (regex değil — substring + keyword set).
Production davranışını taklit etmez; yalnızca sabitlenmiş senaryoları
deterministic ``ExtractedFields`` çıktısına eşler. Yeni senaryo eklenirken
stub'a karşılık gelen anahtar kelime / pattern eklenmelidir.
"""
from __future__ import annotations

import unicodedata

from app.domain.enums import ConversationStep, FinanceType, IntentType
from app.domain.schemas import ConversationStateModel, ExtractedFields


def _fold(text: str) -> str:
    """Türkçe normalize — sadece keyword eşleşmesi için."""
    out = text.replace("İ", "i").replace("I", "i").replace("ı", "i").lower()
    return "".join(c for c in unicodedata.normalize("NFD", out) if not unicodedata.combining(c))


_AFFIRM = ("evet", "onayli", "onayla", "tamam", "kabul", "olur", "confirm")
_REJECT = ("hayir", "iptal", "vazgec", "reddet", "cancel")
_GREET = ("merhaba", "selam", "iyi gunler", "hello", "hi")
_FAQ_KEYWORDS = (
    "nedir",
    "ne kadar",
    "kac",
    "nasil",
    "hangi",
    "neden",
    "oran",
    "limit",
    "yas siniri",
    "kefil ne zaman",
    "max",
    "maksimum",
)


def _has_any(folded: str, words: tuple[str, ...]) -> bool:
    return any(w in folded for w in words)


def _parse_amount(token: str) -> float | None:
    """milyon/bin/sayı parser — sadece test fixture cümlelerini kapsar."""
    t = token.replace(",", ".")
    try:
        if "milyon" in t:
            num = float(t.split("milyon")[0].strip())
            return num * 1_000_000
        if "bin" in t:
            num = float(t.split("bin")[0].strip())
            return num * 1_000
        return float(t)
    except ValueError:
        return None


def _extract_amounts(text: str) -> list[float]:
    """Cümlede 'X milyon', 'Y bin' patternlerini sırasıyla yakalar.

    Bare integer (örn. "1700000") yalnızca metinde finansman/tutar/kredi/talep
    keyword'ü varsa amount olarak kabul edilir; TCKN gibi 11 haneli sayıların
    yanlışlıkla amount sayılmasını önler.
    """
    folded = _fold(text)
    # 11 haneli TCKN benzeri rakamları text'ten çıkar (amount detection için).
    cleaned_tokens: list[str] = []
    for tok in folded.replace(",", ".").split():
        if tok.isdigit() and len(tok) == 11:
            continue
        cleaned_tokens.append(tok)
    allow_bare = any(kw in folded for kw in ("finansman", "tutar", "kredi", "talep", "istiyorum", "yap"))

    amounts: list[float] = []
    i = 0
    while i < len(cleaned_tokens):
        tok = cleaned_tokens[i]
        try:
            num = float(tok)
        except ValueError:
            i += 1
            continue
        unit_idx = i + 1
        if unit_idx < len(cleaned_tokens) and cleaned_tokens[unit_idx].startswith("milyon"):
            sub = num * 1_000_000
            j = unit_idx + 1
            # "X milyon Y bin"
            if j + 1 < len(cleaned_tokens):
                try:
                    nxt = float(cleaned_tokens[j])
                    if cleaned_tokens[j + 1].startswith("bin"):
                        sub += nxt * 1_000
                        i = j + 2
                        amounts.append(sub)
                        continue
                except ValueError:
                    pass
            amounts.append(sub)
            i = unit_idx + 1
            continue
        if unit_idx < len(cleaned_tokens) and cleaned_tokens[unit_idx].startswith("bin"):
            amounts.append(num * 1_000)
            i = unit_idx + 1
            continue
        # Bareword number — sadece finansman/tutar keyword'ü varsa
        if allow_bare and num >= 1000:
            amounts.append(num)
        i += 1
    return amounts


_MODEL_CANDIDATES = (
    ("toyota corolla", "Toyota Corolla"),
    ("ford transit custom", "Ford Transit Custom"),
    ("ford transit", "Ford Transit"),
    ("fiat egea", "Fiat Egea"),
    ("renault clio", "Renault Clio"),
    ("renault megane", "Renault Megane"),
    ("vw polo", "Volkswagen Polo"),
    ("volkswagen polo", "Volkswagen Polo"),
    ("bmw 3", "BMW 3 Series"),
    ("mercedes c", "Mercedes C-Class"),
    ("mercedes sprinter", "Mercedes Sprinter"),
    ("tesla model 3", "Tesla Model 3"),
    ("togg t10x", "Togg T10X"),
    ("fiat doblo", "Fiat Doblo"),
    ("vw crafter", "Volkswagen Crafter"),
    ("renault kangoo", "Renault Kangoo"),
    ("iveco daily", "Iveco Daily"),
    ("lada niva", "Lada Niva"),
)


_STOP_TOKENS = {
    "yeni", "ikinci", "el", "sifir", "0", "km",
    "fatura", "proforma", "kasko", "finansman", "kredi", "tutar", "talep",
    "istiyorum", "milyon", "bin", "tl", "model", "arac", "araç",
    "icin", "için", "olarak",
}


def _detect_model(folded: str) -> str | None:
    """Exact / substring catalog eşleşmesi öncelikli; bulamazsa cümleden
    aday alpha-token grubunu raw döndürür. Raw çıktıyı field_extraction_node
    rapidfuzz ile canonical'a çevirir."""
    for needle, canonical in _MODEL_CANDIDATES:
        if needle in folded:
            return canonical

    # Yazım hatalı / katalogta olmayan aday — "Tyota Korola" gibi.
    # Aday: ardışık iki alpha-token, stop-token olmayan.
    tokens = [t for t in folded.replace(",", " ").replace(".", " ").split() if t]
    candidate: list[str] = []
    best: list[str] = []
    for tok in tokens + [""]:
        if tok and tok.isalpha() and tok not in _STOP_TOKENS:
            candidate.append(tok)
        else:
            if len(candidate) >= 2 and len(candidate) > len(best):
                best = candidate
            candidate = []
    if best:
        return " ".join(best).title()
    return None


_DATE_PATTERNS = (
    "01.06.2023",
    "12.05.2023",
    "01.01.2010",
    "01.06.2010",
    "12.05.2021",
)


def _parse_date_substr(text: str):
    from datetime import date

    for raw in _DATE_PATTERNS:
        if raw in text:
            d, m, y = raw.split(".")
            return date(int(y), int(m), int(d))
    return None


def _detect_tckn(text: str) -> str | None:
    """11 ardışık rakam — yalnızca test fixture'ında geçen TCKN'leri yakalar."""
    digits: list[str] = []
    for ch in text:
        if ch.isdigit():
            digits.append(ch)
        elif digits and len(digits) == 11:
            candidate = "".join(digits)
            digits = []
            return candidate
        else:
            digits = []
    if len(digits) == 11:
        return "".join(digits)
    return None


class StubExtractor:
    """Test-only deterministic extractor. Never used in production."""

    def extract(self, message: str, state: ConversationStateModel) -> ExtractedFields:
        text = message.strip()
        folded = _fold(text)
        out = ExtractedFields()

        # Greeting
        if _has_any(folded, _GREET) and not any(
            kw in folded for kw in ("yeni", "ikinci", "fatura", "kasko", "finansman")
        ):
            out.intent = IntentType.GREET if hasattr(IntentType, "GREET") else IntentType.UNKNOWN
            out.confidence = 0.95
            return out

        # FAQ detection — soru işareti veya FAQ keyword
        if "?" in text or _has_any(folded, _FAQ_KEYWORDS):
            # FAQ olmayan istisna: "evet onaylıyorum" gibi short affirmation
            if not _has_any(folded, _AFFIRM):
                out.intent = IntentType.FAQ_QUESTION
                out.faq_question = text
                out.confidence = 0.9
                return out

        # Finance type
        if "ikinci el" in folded or "2.el" in folded or "2. el" in folded or "kullanilmis" in folded:
            out.finance_type = FinanceType.USED
        elif "yeni" in folded or "sifir" in folded or "0 km" in folded:
            out.finance_type = FinanceType.NEW

        # Confirmation at AWAITING_CONFIRMATION
        if state.current_step == ConversationStep.AWAITING_CONFIRMATION:
            if _has_any(folded, _AFFIRM) and not (
                _detect_amounts := _extract_amounts(text)
            ):
                out.intent = IntentType.CONFIRM
                out.confidence = 0.95
                return out
            if _has_any(folded, _REJECT) and not _extract_amounts(text):
                out.intent = IntentType.REJECT
                out.confidence = 0.9
                return out

        # HGS decision
        if state.current_step == ConversationStep.AWAITING_HGS_DECISION:
            if _has_any(folded, _AFFIRM):
                out.intent = IntentType.HGS_DECISION
                out.field_to_update = "hgs_accepted_yes"
                out.confidence = 0.9
                return out
            if _has_any(folded, _REJECT):
                out.intent = IntentType.HGS_DECISION
                out.field_to_update = "hgs_accepted_no"
                out.confidence = 0.9
                return out

        # Field-update during collection / fix
        if state.current_step in (
            ConversationStep.COLLECTING_FIELDS,
            ConversationStep.AWAITING_FIELD_FIX,
            ConversationStep.AWAITING_CONFIRMATION,
        ):
            amounts = _extract_amounts(text)
            if "tutar" in folded or "finansman" in folded or "kredi" in folded:
                if amounts:
                    out.intent = IntentType.UPDATE_FIELD
                    out.field_to_update = "requested_amount"
                    out.requested_amount = amounts[0]
                    out.confidence = 0.9
                    return out

        # TCKN — kefil/satıcı
        tckn = _detect_tckn(text)
        if tckn:
            if "kefil" in folded:
                out.guarantor_tckn = tckn
            elif "satici" in folded or "satıcı" in text.lower():
                out.seller_tckn = tckn
            else:
                if state.fields.finance_type == FinanceType.NEW:
                    out.guarantor_tckn = tckn
                elif state.fields.finance_type == FinanceType.USED:
                    out.seller_tckn = tckn

        # Vehicle model
        model = _detect_model(folded)
        if model:
            out.vehicle_model = model

        # Registration date
        reg_date = _parse_date_substr(text)
        if reg_date is not None:
            out.registration_date = reg_date

        # Vehicle age e.g. "5 yaşında"
        if "yasinda" in folded or "yaşında" in text.lower():
            for tok in folded.split():
                try:
                    n = int(tok)
                    if 0 < n < 50:
                        out.vehicle_age = n
                        break
                except ValueError:
                    continue

        # Model year — bare 4-digit year between 1990-2100
        for tok in folded.replace(",", " ").split():
            try:
                yr = int(tok)
                if 1990 <= yr <= 2100 and out.registration_date is None and out.vehicle_age is None:
                    out.model_year = yr
                    break
            except ValueError:
                continue

        # Amounts — map by keyword window
        amounts = _extract_amounts(text)
        if amounts:
            mapped = _map_amounts(folded, amounts, out.finance_type or state.fields.finance_type)
            for k, v in mapped.items():
                if getattr(out, k, None) is None:
                    setattr(out, k, v)

        # Intent fallback
        if out.intent == IntentType.UNKNOWN:
            if out.finance_type or any(
                getattr(out, k) is not None
                for k in ("invoice_value", "casco_value", "requested_amount", "vehicle_model", "registration_date")
            ):
                if state.current_step in (
                    ConversationStep.START,
                    ConversationStep.AWAITING_INTENT,
                    ConversationStep.AWAITING_FINANCE_TYPE,
                ):
                    out.intent = IntentType.START_APPLICATION
                else:
                    out.intent = IntentType.PROVIDE_INFO
                out.confidence = 0.85

        return out


def _map_amounts(folded: str, amounts: list[float], finance_type: FinanceType | None) -> dict[str, float]:
    """Sıralama: amount + en yakın keyword."""
    if not amounts:
        return {}
    out: dict[str, float] = {}

    fatura_idx = folded.find("fatura")
    proforma_idx = folded.find("proforma")
    kasko_idx = folded.find("kasko")
    finansman_idx = max(folded.find("finansman"), folded.find("kredi"), folded.find("istiyorum"), folded.find("talep"))

    # If exactly two amounts and a value+requested pair is implied, split by order.
    if len(amounts) == 2:
        if finance_type == FinanceType.USED or kasko_idx >= 0:
            out["casco_value"] = amounts[0]
            out["requested_amount"] = amounts[1]
        else:
            out["invoice_value"] = amounts[0]
            out["requested_amount"] = amounts[1]
        return out

    if len(amounts) == 1:
        if finansman_idx >= 0:
            out["requested_amount"] = amounts[0]
        elif kasko_idx >= 0:
            out["casco_value"] = amounts[0]
        elif fatura_idx >= 0 or proforma_idx >= 0:
            out["invoice_value"] = amounts[0]
        else:
            if finance_type == FinanceType.USED:
                out["casco_value"] = amounts[0]
            else:
                out["invoice_value"] = amounts[0]
        return out

    # 3+ amounts: invoice/casco + requested + leftover
    if finance_type == FinanceType.USED or kasko_idx >= 0:
        out["casco_value"] = amounts[0]
    else:
        out["invoice_value"] = amounts[0]
    out["requested_amount"] = amounts[-1]
    return out
