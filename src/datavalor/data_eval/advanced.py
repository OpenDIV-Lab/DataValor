"""Additional task-neutral DataEval metrics and report gates.

All metrics expose the existing ``MetricResult`` contract.  They are intended
for acceptance tests and research baselines; monetary value is intentionally
out of scope.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, number, result, rows
from .interfaces import QualityMetric
from .models import EvaluationReport, ScoreDirection


class NumericRangeComplianceMetric(QualityMetric):
    """Fraction of finite values inside an explicit business range."""

    def __init__(self, field: str = "value", minimum: float | None = 0.0, maximum: float | None = 1.0, inclusive: bool = True):
        if minimum is None and maximum is None:
            raise ValueError("at least one range bound is required")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum cannot exceed maximum")
        self.field, self.minimum, self.maximum, self.inclusive = field, minimum, maximum, inclusive

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("tabular.numeric_range", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "range", "constraints"))

    def compute(self, product, request, context):
        data = rows(product, request); valid, invalid = 0, []
        for index, row in enumerate(data):
            value = number(row.get(self.field))
            lower_ok = value is not None and (self.minimum is None or (value >= self.minimum if self.inclusive else value > self.minimum))
            upper_ok = value is not None and (self.maximum is None or (value <= self.maximum if self.inclusive else value < self.maximum))
            if value is not None and lower_ok and upper_ok:
                valid += 1
            else:
                invalid.append({"row": index, "value": row.get(self.field), "reason": "missing_or_out_of_range"})
        return result(self.spec.name, "range_compliance", request, product, valid / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"field": self.field, "record_count": len(data), "valid_count": valid, "invalid_count": len(invalid), "minimum": self.minimum, "maximum": self.maximum, "inclusive": self.inclusive}, evidence_items=invalid)


class LabelConflictMetric(QualityMetric):
    """Detect duplicate entity IDs assigned contradictory labels."""

    def __init__(self, id_field: str = "id", label_field: str = "label"):
        self.id_field, self.label_field = id_field, label_field

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("tabular.label_conflict", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "labels", "consistency"))

    def compute(self, product, request, context):
        data = rows(product, request); labels: dict[str, set[str]] = defaultdict(set)
        for row in data:
            if row.get(self.id_field) is not None and row.get(self.label_field) is not None:
                labels[str(row[self.id_field])].add(str(row[self.label_field]))
        conflicts = [{"id": identifier, "labels": tuple(sorted(values))} for identifier, values in sorted(labels.items()) if len(values) > 1]
        affected = sum(1 for identifier, values in labels.items() if len(values) > 1)
        return result(self.spec.name, "label_consistency", request, product, 1 - affected / len(labels) if labels else 1.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"id_field": self.id_field, "label_field": self.label_field, "entity_count": len(labels), "conflict_count": len(conflicts), "affected_entity_count": affected}, evidence_items=conflicts)


class GroupCompletenessParityMetric(QualityMetric):
    """Measure the largest completeness gap between configured groups."""

    def __init__(self, group_field: str = "group", required_fields: Sequence[str] = ("value",)):
        if not required_fields:
            raise ValueError("required_fields cannot be empty")
        self.group_field, self.required_fields = group_field, tuple(required_fields)

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("tabular.group_completeness_parity", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "group", "fairness"))

    def compute(self, product, request, context):
        data = rows(product, request); grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in data:
            grouped[str(row.get(self.group_field, "<missing>"))].append(row)
        scores = {group: sum(all(row.get(field) is not None for field in self.required_fields) for row in group_rows) / len(group_rows) for group, group_rows in grouped.items() if group_rows}
        gap = max(scores.values()) - min(scores.values()) if scores else 0.0
        return result(self.spec.name, "group_completeness_gap", request, product, gap, ScoreDirection.LOWER_IS_BETTER, context, statistics={"group_field": self.group_field, "required_fields": self.required_fields, "group_scores": scores, "group_count": len(scores), "max_gap": gap})


_SENTENCE = re.compile(r"[^.!?]+[.!?]?")
_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)


class TextReadabilityMetric(QualityMetric):
    """Compute a dependency-free Flesch-style readability estimate."""

    def __init__(self, text_field: str = "text"):
        self.text_field = text_field

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("text.readability", "1.0.0", "data_eval", "quality_metric", capabilities=("text", "readability"))

    @staticmethod
    def _syllables(word: str) -> int:
        groups = re.findall(r"[aeiouy]+", word.casefold())
        count = max(1, len(groups))
        if word.casefold().endswith("e") and count > 1:
            count -= 1
        return count

    def compute(self, product, request, context):
        data = rows(product, request); scores: list[float] = []; evidence = []
        for index, row in enumerate(data):
            text = str(row.get(self.text_field) or ""); words = _WORD.findall(text); sentences = [part for part in _SENTENCE.findall(text) if part.strip()]
            syllables = sum(self._syllables(word) for word in words)
            raw = 206.835 - 1.015 * (len(words) / max(1, len(sentences))) - 84.6 * (syllables / max(1, len(words))) if words else 0.0
            score = clamp(raw / 100.0)
            scores.append(score)
            if raw < 30 and words:
                evidence.append({"row": index, "flesch": raw, "word_count": len(words)})
        return result(self.spec.name, "text_readability", request, product, sum(scores) / len(scores) if scores else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "mean_flesch_normalized": sum(scores) / len(scores) if scores else 0.0, "low_readability_count": len(evidence), "text_field": self.text_field}, evidence_items=evidence)


class EvaluationThresholdGate:
    """Evaluate report metrics against explicit lower/upper bounds.

    Returns a serializable mapping rather than changing ``EvaluationReport``;
    this keeps the existing composite output backward compatible.
    """

    def evaluate(self, report: EvaluationReport, thresholds: Mapping[str, float], *, default_direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER) -> Mapping[str, Any]:
        checks = []
        for metric in report.metrics:
            if metric.name not in thresholds or metric.value is None:
                continue
            threshold = float(thresholds[metric.name]); direction = metric.direction or default_direction
            passed = metric.value >= threshold if direction is ScoreDirection.HIGHER_IS_BETTER else metric.value <= threshold if direction is ScoreDirection.LOWER_IS_BETTER else True
            checks.append({"metric": metric.name, "value": metric.value, "threshold": threshold, "direction": direction.value, "passed": passed})
        failed = [check for check in checks if not check["passed"]]
        return {"status": "passed" if not failed else "failed", "checked": len(checks), "failed": len(failed), "checks": tuple(checks)}


__all__ = ["NumericRangeComplianceMetric", "LabelConflictMetric", "GroupCompletenessParityMetric", "TextReadabilityMetric", "EvaluationThresholdGate"]
