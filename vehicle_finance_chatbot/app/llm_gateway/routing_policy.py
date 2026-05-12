"""Per-node routing + token budgets.

The aliases here MUST exist in ``infra/litellm/config.yaml`` as
``model_name`` entries. The gateway never references concrete model IDs.
"""
from __future__ import annotations

from app.llm_gateway.exceptions import RoutingError
from app.llm_gateway.schemas import NodePolicy

# Node purposes used by the LangGraph nodes. Keep these stable — admin
# dashboards and budget alarms key off these strings.
NODE_INTENT = "intent_classification"
NODE_FIELD = "field_extraction"
NODE_FAQ = "faq_answer"
NODE_SUMMARY = "final_summary"
NODE_SAFETY = "safety_check"
NODE_RESPONSE = "response_generation"


NODE_BUDGETS: dict[str, NodePolicy] = {
    NODE_INTENT: NodePolicy(
        name=NODE_INTENT,
        model_alias="vehicle-finance-small",
        max_input_tokens=800,
        max_output_tokens=120,
        temperature=0.0,
        fallback_alias="vehicle-finance-large",
    ),
    NODE_FIELD: NodePolicy(
        name=NODE_FIELD,
        model_alias="vehicle-finance-small",
        max_input_tokens=1200,
        max_output_tokens=300,
        temperature=0.0,
        fallback_alias="vehicle-finance-large",
    ),
    NODE_FAQ: NodePolicy(
        name=NODE_FAQ,
        model_alias="vehicle-finance-large",
        max_input_tokens=3500,
        max_output_tokens=700,
        max_context_chunks=4,
        temperature=0.1,
    ),
    NODE_SUMMARY: NodePolicy(
        name=NODE_SUMMARY,
        model_alias="vehicle-finance-small",
        max_input_tokens=1200,
        max_output_tokens=350,
        temperature=0.1,
        fallback_alias="vehicle-finance-large",
    ),
    NODE_SAFETY: NodePolicy(
        name=NODE_SAFETY,
        model_alias="vehicle-finance-guard",
        max_input_tokens=1000,
        max_output_tokens=100,
        temperature=0.0,
    ),
    NODE_RESPONSE: NodePolicy(
        name=NODE_RESPONSE,
        model_alias="vehicle-finance-small",
        max_input_tokens=1500,
        max_output_tokens=400,
        temperature=0.2,
    ),
}


def get_policy(node_purpose: str) -> NodePolicy:
    try:
        return NODE_BUDGETS[node_purpose]
    except KeyError as exc:
        raise RoutingError(f"unknown node_purpose={node_purpose!r}") from exc
