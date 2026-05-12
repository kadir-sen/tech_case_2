"""Cheap input-token estimator.

Uses tiktoken when available (OpenAI-compatible cl100k_base) for an
accurate count. Falls back to a chars/4 heuristic — good enough for
budget guardrails since we always leave headroom.
"""
from __future__ import annotations

try:
    import tiktoken  # type: ignore

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str | None) -> int:
        if not text:
            return 0
        return len(_ENC.encode(text))

    _BACKEND = "tiktoken"
except Exception:  # pragma: no cover - tiktoken optional

    def count_tokens(text: str | None) -> int:
        if not text:
            return 0
        # Conservative: 1 token per ~4 chars in English/Turkish mixed text.
        return max(1, len(text) // 4)

    _BACKEND = "heuristic"


def backend_name() -> str:
    return _BACKEND
