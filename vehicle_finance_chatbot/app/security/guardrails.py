from __future__ import annotations

import re
from dataclasses import dataclass

# Prompt-injection patterns. Designed to be conservative — false positives
# only produce a safe-reply, they do not corrupt application state.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # English
        r"ignore (all )?previous (instructions|prompt)",
        r"disregard (your|the) (instructions|prompt|rules)",
        r"reveal (the |your )?system prompt",
        r"show (me )?(the )?system prompt",
        r"act as (a )?(developer|admin|root)",
        r"developer mode",
        r"jailbreak",
        r"bypass (the )?(rules|limits|policy|restriction)",
        # Turkish — instruction subversion
        r"(\bönceki|tüm)\s+talimat(lar)?(ı|i)\s+(unut|yok say|ignore|bo[şs]ver)",
        r"(kurallar(ı|i))\s+(yok say|by ?pass|aş|bo[şs]ver|unut)",
        r"sistem promptunu (göster|ver|paylas|paylaş)",
        r"sistem talimat(ı|larını)",
        r"tüm müşterilerin (bilgi|tckn|veri)",
        r"limit(leri|i)\s*(by ?pass|aş|yok say|unut|bo[şs]ver|kaldır)",
        r"admin moduna\s+(geç|gec)",
        r"(geliştirici|gelistirici) moduna",
        r"kurallar(ı|i)\s+bo[şs]ver",
        r"kural(ı|i) (umursama|takma)",
        # SQL/data extraction hints
        r"select \*\s*from",
        r"drop table",
        r"union\s+select",
    )
)

_SUSPICIOUS_TOKENS: tuple[str, ...] = (
    "<<sys>>",
    "<|im_start|>",
    "<|system|>",
    "###system",
    "[system]",
)


@dataclass(frozen=True)
class GuardrailResult:
    blocked: bool
    reason: str | None = None
    safe_reply: str | None = None


def check_user_input(message: str) -> GuardrailResult:
    if not message:
        return GuardrailResult(blocked=False)
    lower = message.lower()
    for token in _SUSPICIOUS_TOKENS:
        if token in lower:
            return GuardrailResult(
                blocked=True,
                reason="suspicious_token",
                safe_reply=_safe_reply(),
            )
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            return GuardrailResult(
                blocked=True,
                reason="prompt_injection_pattern",
                safe_reply=_safe_reply(),
            )
    return GuardrailResult(blocked=False)


def check_retrieved_context(chunks: list[str]) -> list[str]:
    """Strip prompt-injection lines from retrieved documents before they
    are passed into a prompt. We do not let document content reissue
    instructions to the model.
    """
    cleaned: list[str] = []
    for chunk in chunks:
        out_lines: list[str] = []
        for line in chunk.splitlines():
            if any(p.search(line) for p in _INJECTION_PATTERNS):
                continue
            out_lines.append(line)
        cleaned.append("\n".join(out_lines))
    return cleaned


def _safe_reply() -> str:
    return (
        "Bu talep, taşıt finansmanı ön başvuru asistanının kapsamı dışındadır. "
        "Yardımcı olabileceğim taşıt finansmanı başvurunuza dönelim. "
        "Yeni mi yoksa ikinci el araç için mi başvuru yapmak istersiniz?"
    )


# Tool allowlist — the LLM may only request tools whose names are listed here.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "extract_fields",
        "validate_new_application",
        "validate_used_application",
        "retrieve_faq",
        "create_application_after_confirmation",
        "create_hgs_lead",
        "handoff_to_human",
    }
)


def is_tool_allowed(name: str) -> bool:
    return name in ALLOWED_TOOLS
