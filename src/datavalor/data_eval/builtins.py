"""Concrete standard-library quality metrics and a composite evaluator."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, canonical_sha256

from .interfaces import DataEvaluator, QualityMetric
from .models import EvaluationReport, EvaluationRequest, MetricResult, ScoreDirection
from .operators import _records


class CompletenessMetric(QualityMetric):
    """Ratio of non-null cells, optionally restricted to selected fields."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.completeness", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "completeness"))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = _records(product, request)
        fields = tuple(request.options.get("fields", ())) or tuple(sorted({str(key) for row in rows for key in row}))
        cells = len(rows) * len(fields)
        missing = sum(row.get(field) is None for row in rows for field in fields)
        score = (cells - missing) / cells if cells else 0.0
        return MetricResult(self.spec.name, "completeness", request.scope, score, ScoreDirection.HIGHER_IS_BETTER, unit="ratio", target_id=product.product_id, statistics={"record_count": len(rows), "field_count": len(fields), "cell_count": cells, "missing_cells": missing}, evidence=(Evidence("computed.cells", summary=f"检查 {cells} 个字段单元"),), diagnostics={"run_id": context.run_id})


class DuplicateRateMetric(QualityMetric):
    """Fraction of duplicate records using canonical JSON equality."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.duplicate_rate", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "duplicates"))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = _records(product, request)
        # Canonical JSON makes equality independent of dictionary insertion
        # order and handles nested values more reliably than ``repr``.
        keys = [canonical_sha256(dict(row)) for row in rows]
        duplicate_count = len(keys) - len(set(keys))
        rate = duplicate_count / len(rows) if rows else 0.0
        return MetricResult(self.spec.name, "uniqueness", request.scope, rate, ScoreDirection.LOWER_IS_BETTER, unit="ratio", target_id=product.product_id, statistics={"record_count": len(rows), "duplicate_count": duplicate_count, "unique_count": len(set(keys))}, diagnostics={"run_id": context.run_id})


class FieldValidityMetric(QualityMetric):
    """Validate required fields and simple type/range constraints."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.field_validity", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "schema"))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = _records(product, request)
        required = tuple(request.options.get("required_fields", ()))
        types = request.options.get("field_types", {})
        invalid: list[dict[str, Any]] = []
        checked = 0
        for index, row in enumerate(rows):
            for field in required:
                checked += 1
                if field not in row or row[field] is None:
                    invalid.append({"row": index, "field": field, "reason": "missing"})
            for field, expected in types.items():
                checked += 1
                if field not in row or row[field] is None:
                    invalid.append({"row": index, "field": field, "reason": "missing"})
                elif not self._matches(row[field], str(expected)):
                    invalid.append({"row": index, "field": field, "reason": f"expected_{expected}"})
        score = 1.0 - len(invalid) / checked if checked else 1.0
        evidence = tuple(Evidence("field.validity", summary=str(item), metadata=item) for item in invalid[:100])
        return MetricResult(self.spec.name, "validity", request.scope, max(0.0, score), ScoreDirection.HIGHER_IS_BETTER, unit="ratio", target_id=product.product_id, statistics={"checked": checked, "invalid": len(invalid)}, evidence=evidence, diagnostics={"run_id": context.run_id, "evidence_truncated": len(invalid) > 100})

    @staticmethod
    def _matches(value: Any, expected: str) -> bool:
        return {"string": isinstance(value, str), "number": isinstance(value, (int, float)) and not isinstance(value, bool), "boolean": isinstance(value, bool), "integer": isinstance(value, int) and not isinstance(value, bool)}.get(expected, False)


class CompositeEvaluator(DataEvaluator):
    """Run several metrics and retain each result without flattening meaning."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.composite_evaluator", "1.0.0", "data_eval", "evaluator", capabilities=("multi_metric", "evidence"))

    def evaluate(self, product: DataProduct, request: EvaluationRequest, metrics: Sequence[QualityMetric], context: RunContext) -> EvaluationReport:
        results: list[MetricResult] = []
        failures: list[dict[str, str]] = []
        for metric in metrics:
            try:
                results.append(metric.compute(product, request, context))
            except Exception as exc:
                failures.append({"metric": metric.spec.name, "error_type": type(exc).__name__, "message": str(exc)})
        status = "succeeded" if not failures else "partial" if results else "failed"
        return EvaluationReport(product.product_id, tuple(results), request.task.task_id if request.task else None, summary={"status": status, "metric_count": len(results), "failure_count": len(failures)}, diagnostics={"run_id": context.run_id, "failures": tuple(failures)})


__all__ = ["CompletenessMetric", "CompositeEvaluator", "DuplicateRateMetric", "FieldValidityMetric"]
