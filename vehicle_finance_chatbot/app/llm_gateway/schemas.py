from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class NodePolicy:
    """Per-node inference policy.

    The ``model_alias`` resolves to a LiteLLM deployment name from
    ``infra/litellm/config.yaml``. Aliases (not concrete model IDs) are
    used so model swaps don't touch application code.
    """

    name: str
    model_alias: str
    max_input_tokens: int
    max_output_tokens: int
    max_context_chunks: int = 3
    temperature: float = 0.1
    fallback_alias: str | None = None


@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage
    model_name: str
    provider: str
    latency_ms: int
    litellm_call_id: str | None = None
    structured_output: Any = None
    trimmed_context_count: int = 0
    fallback_used: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
