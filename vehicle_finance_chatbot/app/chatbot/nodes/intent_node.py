from __future__ import annotations

from app.chatbot.chains.extraction_chain import get_extractor
from app.chatbot.state import GraphState


_extractor = None


def get_default_extractor():
    """Lazy singleton — testler monkeypatch'le sıfırlamak için
    ``reset_default_extractor()`` kullanabilir."""
    global _extractor
    if _extractor is None:
        _extractor = get_extractor()
    return _extractor


def reset_default_extractor() -> None:
    global _extractor
    _extractor = None


def intent_node(graph_state: GraphState) -> GraphState:
    extractor = get_default_extractor()
    graph_state.extracted = extractor.extract(graph_state.user_message, graph_state.state)
    return graph_state
