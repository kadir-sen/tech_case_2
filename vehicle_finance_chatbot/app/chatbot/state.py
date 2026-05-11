from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.schemas import (
    ChatAction,
    ConversationStateModel,
    CustomerProfile,
    ExtractedFields,
)


@dataclass
class GraphState:
    """Runtime state passed between LangGraph nodes.

    We don't mutate the persisted state model in-place during graph
    execution; instead, nodes update fields on this dataclass and the final
    response builder snapshots the result back into ``ConversationStateModel``.
    """

    user_message: str
    state: ConversationStateModel
    customer: CustomerProfile | None = None
    idempotency_key: str | None = None

    extracted: ExtractedFields | None = None
    reply_parts: list[str] = field(default_factory=list)
    actions: list[ChatAction] = field(default_factory=list)
    guardrail_blocked: bool = False
    needs_persist: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_reply(self, text: str) -> None:
        self.reply_parts.append(text.strip())

    def reply(self) -> str:
        return "\n\n".join(p for p in self.reply_parts if p)

    def add_action(self, action: ChatAction) -> None:
        self.actions.append(action)
