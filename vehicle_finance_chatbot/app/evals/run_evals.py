"""Lightweight eval runner.

Runs the canned conversation flows against the live LangGraph workflow
and the canned adversarial messages against the input guardrail. The
output is a small JSON report — enough to gate CI and spot regressions
without needing a heavyweight eval framework.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

# Bootstrap test-style env BEFORE importing app modules.
TMP_DB = Path(tempfile.gettempdir()) / "vfc_eval.db"
if TMP_DB.exists():
    TMP_DB.unlink()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP_DB}")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUDIT_LOG_PATH", str(Path(tempfile.gettempdir()) / "vfc_eval_audit.log"))

from app.auth.mock_customer_store import get_customer  # noqa: E402
from app.chatbot.graph import run_turn  # noqa: E402
from app.chatbot.state import GraphState  # noqa: E402
from app.domain.enums import FinanceType  # noqa: E402
from app.domain.schemas import ConversationStateModel  # noqa: E402
from app.evals.metrics import EvalReport  # noqa: E402
from app.persistence.database import init_db  # noqa: E402
from app.persistence.repositories import ConversationRepository  # noqa: E402
from app.rag.retriever import FaqRetriever  # noqa: E402
from app.security.guardrails import check_user_input  # noqa: E402

init_db()

_repo = ConversationRepository()


def _run_conversation(case: dict) -> dict:
    sid = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
    customer = get_customer("CUST001")
    application_id = None
    duplicate_prevented = False
    seen_app_ids: set[str] = set()
    final_state: ConversationStateModel | None = None

    for turn in case["turns"]:
        state = _repo.load(sid) or ConversationStateModel(session_id=sid, customer_id="CUST001")
        state.customer_id = "CUST001"
        gs = GraphState(user_message=turn, state=state, customer=customer)
        run_turn(gs)
        _repo.save(state)
        if state.application_id:
            if state.application_id in seen_app_ids:
                duplicate_prevented = True
            seen_app_ids.add(state.application_id)
            application_id = state.application_id
        final_state = state

    return {
        "application_id": application_id,
        "duplicate_prevented": duplicate_prevented,
        "state": final_state.model_dump(mode="json") if final_state else {},
    }


def _evaluate(case: dict, result: dict, report: EvalReport) -> None:
    exp = case.get("expected", {})
    cid = case["id"]
    state = result["state"]

    # Intent / finance_type
    if "finance_type" in exp:
        expected_ft = exp["finance_type"]
        actual_ft = state.get("fields", {}).get("finance_type")
        report.intent_accuracy.record(cid, actual_ft == expected_ft)

    # End-to-end completion
    if "creates_application" in exp:
        creates = result["application_id"] is not None
        report.end_to_end_completion.record(cid, creates == exp["creates_application"])

    # Validation correctness (rejection scenarios)
    if "validation_error_substring" in exp:
        last_val = state.get("last_validation") or {}
        errs = " ".join(last_val.get("errors", []))
        report.validation_correctness.record(cid, exp["validation_error_substring"] in errs)
    elif "max_allowed_amount" in exp:
        last_val = state.get("last_validation") or {}
        ok = abs(float(last_val.get("max_allowed_amount") or 0) - float(exp["max_allowed_amount"])) < 1
        report.validation_correctness.record(cid, ok)

    # Field extraction subset
    field_checks: list[bool] = []
    for k in ("requested_amount", "casco_value", "invoice_value"):
        if k in exp:
            field_checks.append(state.get("fields", {}).get(k) == exp[k])
    if "seller_tckn_skipped" in exp:
        field_checks.append(state.get("fields", {}).get("seller_tckn_intent_skipped") == exp["seller_tckn_skipped"])
    if field_checks:
        report.field_extraction.record(cid, all(field_checks))

    # Duplicate prevention
    if exp.get("duplicate_prevented"):
        report.duplicate_prevention.record(cid, result["duplicate_prevented"])

    # Requires guarantor
    if exp.get("requires_guarantor"):
        last_val = state.get("last_validation") or {}
        report.validation_correctness.record(cid, last_val.get("requires_guarantor") is True)


def _eval_faq_retrieval(report: EvalReport) -> None:
    retr = FaqRetriever.instance()
    cases = [
        ("ikinci el oran 40", "%40"),
        ("yeni araç 60 limit", "%60"),
        ("kefil ne zaman gerekli", "kefil"),
        ("5 yaş üstü", "5"),
        ("HGS nedir", "HGS"),
    ]
    for query, expected_token in cases:
        hits = retr.search(query, k=3).hits
        ok = any(expected_token.lower() in h.document.text.lower() for h in hits)
        report.faq_retrieval.record(query, ok)


def _eval_adversarial(report: EvalReport, path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        res = check_user_input(case["message"])
        report.guardrails.record(case["id"], res.blocked == case["expected_blocked"])


def main() -> int:
    base = Path(__file__).parent / "datasets"
    conv_path = base / "conversations.jsonl"
    adv_path = base / "adversarial.jsonl"

    report = EvalReport()

    for line in conv_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        try:
            result = _run_conversation(case)
            _evaluate(case, result, report)
        except Exception as exc:  # noqa: BLE001 - eval should keep going
            print(f"[!] {case['id']}: {exc}")
            report.end_to_end_completion.record(case["id"], False)

    _eval_faq_retrieval(report)
    _eval_adversarial(report, adv_path)

    summary = report.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Return non-zero exit if any metric falls below threshold.
    thresholds = {
        "validation_correctness": 1.0,
        "end_to_end_completion": 0.95,
        "guardrails": 1.0,
        "duplicate_prevention": 1.0,
    }
    failed = [
        m
        for m, t in thresholds.items()
        if summary[m]["total"] and summary[m]["rate"] < t
    ]
    if failed:
        print(f"[X] Below threshold: {failed}")
        return 1
    print("[OK] All eval thresholds met.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
