"""Task-conditioned market demand fit and evidence confidence."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Mapping

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext

from .interfaces import DataEvaluator, QualityMetric
from .models import EvaluationReport, EvaluationRequest, MetricResult, ScoreDirection


class DemandFitEvaluator(DataEvaluator):
    """Score explicit hard requirements and soft buyer preferences."""
    @property
    def spec(self): return ComponentSpec("market.demand_fit", "1.0.0", "data_eval", "evaluator", capabilities=("task", "demand_fit", "market"))
    def evaluate(self, product: DataProduct, request: EvaluationRequest, metrics: Sequence[QualityMetric], context: RunContext) -> EvaluationReport:
        observed = dict(request.options.get("observed", {})); requirements = dict(request.options.get("requirements", request.task.constraints if request.task else {})); weights = dict(request.options.get("weights", {})); hard = set(request.options.get("hard_requirements", ()))
        results: list[MetricResult] = [metric.compute(product, request, context) for metric in metrics]
        checks = []
        for name, expected in requirements.items():
            actual = observed.get(name, product.metadata.get(name)); passed, score = self._compare(actual, expected)
            checks.append((str(name), actual, expected, passed, score, name in hard))
            results.append(MetricResult(f"demand_fit.{name}", "demand_fit", request.scope, score, ScoreDirection.HIGHER_IS_BETTER, "ratio", product.product_id, {"actual": actual, "expected": expected, "passed": passed, "hard": name in hard}, (Evidence("demand.requirement", summary=f"{name}: {passed}", metadata={"name": name, "passed": passed}),), {"run_id": context.run_id}))
        total_weight = sum(max(0.0, float(weights.get(name, 1.0))) for name, *_ in checks)
        fit = sum(score * max(0.0, float(weights.get(name, 1.0))) for name, _, _, _, score, _ in checks) / total_weight if total_weight else 1.0
        hard_failures = tuple(name for name, _, _, passed, _, is_hard in checks if is_hard and not passed)
        status = "failed" if hard_failures else "conditional" if any(not item[3] for item in checks) else "passed"
        return EvaluationReport(product.product_id, tuple(results), request.task.task_id if request.task else None, summary={"status": status, "demand_fit_score": fit, "requirement_count": len(checks), "hard_failures": hard_failures}, diagnostics={"run_id": context.run_id, "weights": weights})
    @staticmethod
    def _compare(actual, expected):
        if isinstance(expected, Mapping):
            if actual is None: return False, 0.0
            if "min" in expected and float(actual) < float(expected["min"]): return False, max(0.0, float(actual) / float(expected["min"])) if float(expected["min"]) else 0.0
            if "max" in expected and float(actual) > float(expected["max"]): return False, max(0.0, float(expected["max"]) / float(actual)) if float(actual) else 0.0
            return True, 1.0
        if isinstance(expected, (list, tuple, set)): 
            passed = set(expected).issubset(set(actual or ())) if isinstance(actual, (list, tuple, set)) else actual in expected
            return passed, 1.0 if passed else 0.0
        passed = actual == expected
        return passed, 1.0 if passed else 0.0


class EvaluationConfidenceEstimator:
    """Estimate evidence confidence from sample size, coverage and variability."""
    def estimate(self, report: EvaluationReport, *, sample_size: int, population_size: int | None = None, sampling_quality: float = 1.0) -> Mapping[str, Any]:
        if sample_size < 0: raise ValueError("sample_size must be non-negative")
        if not 0 <= sampling_quality <= 1: raise ValueError("sampling_quality must be in [0, 1]")
        coverage = min(1.0, sample_size / population_size) if population_size and population_size > 0 else 1.0 - math.exp(-sample_size / 100.0)
        measurable = [metric for metric in report.metrics if metric.value is not None]
        metric_coverage = len(measurable) / len(report.metrics) if report.metrics else 0.0
        confidence = math.sqrt(max(0.0, coverage * metric_coverage)) * sampling_quality
        return {"confidence": min(1.0, confidence), "level": "high" if confidence >= 0.8 else "medium" if confidence >= 0.5 else "low", "sample_size": sample_size, "population_size": population_size, "sample_coverage": coverage, "metric_coverage": metric_coverage, "sampling_quality": sampling_quality}


__all__ = ["DemandFitEvaluator", "EvaluationConfidenceEstimator"]
