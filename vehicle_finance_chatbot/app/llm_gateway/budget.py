"""Token-budget enforcement.

Pre-call we estimate prompt tokens and trim context (RAG chunks +
conversation history) until we fit. If we still don't fit, we raise
``BudgetExceededError`` — the caller is expected to fall back to a safe
deterministic response rather than make an expensive call we can't bound.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.llm_gateway.schemas import NodePolicy
from app.llm_gateway.token_counter import count_tokens

# Reserve some tokens for chat envelope / structured-output instructions.
_PROMPT_OVERHEAD_TOKENS = 50


@dataclass(frozen=True)
class FitResult:
    chunks_kept: list[str]
    history_kept: list[str]
    estimated_prompt_tokens: int
    chunks_dropped: int
    history_dropped: int

    @property
    def trimmed(self) -> bool:
        return self.chunks_dropped > 0 or self.history_dropped > 0


def fit_to_budget(
    *,
    policy: NodePolicy,
    system_prompt: str,
    user_message: str,
    context_chunks: list[str] | None = None,
    history_messages: list[str] | None = None,
) -> FitResult:
    """Greedy fit: keep most-recent history and highest-ranked chunks first.

    We trim history before chunks because chunk relevance is curated by
    the retriever, while history is naturally redundant.
    """
    chunks = list(context_chunks or [])
    history = list(history_messages or [])

    base = count_tokens(system_prompt) + count_tokens(user_message) + _PROMPT_OVERHEAD_TOKENS
    headroom = max(0, policy.max_input_tokens - base)

    # Trim history first (keep tail).
    history_kept: list[str] = []
    history_used = 0
    for msg in reversed(history):
        cost = count_tokens(msg)
        if history_used + cost > headroom // 3:  # at most 1/3 of headroom for history
            continue
        history_kept.insert(0, msg)
        history_used += cost
    history_dropped = len(history) - len(history_kept)
    headroom -= history_used

    # Keep highest-ranked chunks until cap.
    chunks_kept: list[str] = []
    chunks_used = 0
    for chunk in chunks[: policy.max_context_chunks]:
        cost = count_tokens(chunk)
        if chunks_used + cost > headroom:
            break
        chunks_kept.append(chunk)
        chunks_used += cost
    chunks_dropped = len(chunks) - len(chunks_kept)

    estimated = base + history_used + chunks_used
    return FitResult(
        chunks_kept=chunks_kept,
        history_kept=history_kept,
        estimated_prompt_tokens=estimated,
        chunks_dropped=chunks_dropped,
        history_dropped=history_dropped,
    )
