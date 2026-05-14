"""Greeting node — chatbot açılır açılmaz tetiklenir.

Kullanıcının `full_name` ve `gender` bilgisi customer-master'dan zaten
geliyor. Bu yüzden greeting **deterministic template** ile üretilir —
LLM çağrılmaz. Tek doldurulan iki slot:
- `{first_name}` → `full_name`'in ilk kelimesi
- `{honorific}`  → `gender=="FEMALE"` ise "Hanım", aksi halde "Bey"

Geri kalan metin sabittir ve "FAQ" kelimesini içermez (case'in tek-amaçlı
asistan tonu). Müşteri profili gelmeyen kenar durumlar için generic bir
fallback selamlama döner.
"""
from __future__ import annotations

from app.chatbot.state import GraphState
from app.domain.enums import ActionType, ConversationStep
from app.domain.schemas import ChatAction, CustomerProfile


_GENERIC_BODY = (
    "taşıt finansmanı ön başvurunuza yardımcı olacağım. "
    "Yeni bir araç mı yoksa ikinci el bir araç mı düşünüyorsunuz? "
    "Henüz karar veremediyseniz araç finansmanı hakkında dilediğinizi bana danışabilirsiniz."
)


def _honorific(gender: str) -> str:
    return "Hanım" if gender == "FEMALE" else "Bey"


def _build_greeting(customer: CustomerProfile | None) -> str:
    if customer is None or not customer.full_name:
        return f"Merhaba, {_GENERIC_BODY}"
    first_name = customer.full_name.split()[0]
    honorific = _honorific(customer.gender)
    return f"Merhaba {first_name} {honorific}, {_GENERIC_BODY}"


def greeting_node(graph_state: GraphState) -> GraphState:
    state = graph_state.state
    greeting = _build_greeting(graph_state.customer)
    graph_state.add_reply(greeting)
    graph_state.add_action(ChatAction(type=ActionType.SHOW_GREETING))
    state.current_step = ConversationStep.GREETED
    return graph_state
