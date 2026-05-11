from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricCounters:
    total: int = 0
    passed: int = 0
    failed_cases: list[str] = field(default_factory=list)

    def record(self, case_id: str, ok: bool) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failed_cases.append(case_id)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class EvalReport:
    intent_accuracy: MetricCounters = field(default_factory=MetricCounters)
    field_extraction: MetricCounters = field(default_factory=MetricCounters)
    validation_correctness: MetricCounters = field(default_factory=MetricCounters)
    faq_retrieval: MetricCounters = field(default_factory=MetricCounters)
    end_to_end_completion: MetricCounters = field(default_factory=MetricCounters)
    guardrails: MetricCounters = field(default_factory=MetricCounters)
    duplicate_prevention: MetricCounters = field(default_factory=MetricCounters)

    def summary(self) -> dict[str, dict[str, float | int | list[str]]]:
        return {
            name: {
                "total": getattr(self, name).total,
                "passed": getattr(self, name).passed,
                "rate": round(getattr(self, name).rate, 4),
                "failed": getattr(self, name).failed_cases,
            }
            for name in (
                "intent_accuracy",
                "field_extraction",
                "validation_correctness",
                "faq_retrieval",
                "end_to_end_completion",
                "guardrails",
                "duplicate_prevention",
            )
        }
