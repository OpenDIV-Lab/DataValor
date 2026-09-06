"""Dependency-free tabular evaluation metrics.

The metrics follow common data-centric ML practice: missingness, schema
consistency, label balance and robust IQR outlier detection are reported
separately so downstream valuation can choose task-specific weights.
"""

from __future__ import annotations

import math
from collections import Counter

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, describe, finite_numbers, result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection


class TabularSchemaConsistencyMetric(QualityMetric):
    """Fraction of records matching the inferred or requested field schema."""

    def __init__(self, required_fields=(), field_types=None):
        self.required_fields = tuple(required_fields)
        self.field_types = dict(field_types or {})

    @property
    def spec(self):
        return ComponentSpec("tabular.schema_consistency", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "schema"))

    def compute(self, product, request, context):
        data = rows(product, request)
        required = tuple(request.options.get("required_fields", self.required_fields))
        types = dict(request.options.get("field_types", self.field_types))
        invalid = []
        checked = 0
        for index, row in enumerate(data):
            for field in required:
                checked += 1
                if field not in row or row[field] is None:
                    invalid.append({"row": index, "field": field, "reason": "missing"})
            for field, expected in types.items():
                checked += 1
                value = row.get(field)
                if value is None:
                    invalid.append({"row": index, "field": field, "reason": "missing"})
                elif not self._matches(value, str(expected)):
                    invalid.append({"row": index, "field": field, "reason": f"expected_{expected}"})
        score = 1.0 - len(invalid) / checked if checked else 1.0
        return result(self.spec.name, "schema_consistency", request, product, clamp(score), ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "checked": checked, "invalid": len(invalid)}, evidence_items=invalid, diagnostics={"evidence_truncated": len(invalid) > 100})

    @staticmethod
    def _matches(value, expected):
        if expected in {"number", "float"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "string":
            return isinstance(value, str)
        if expected == "boolean":
            return isinstance(value, bool)
        return False


class TabularNumericStatisticsMetric(QualityMetric):
    """Distribution and finite-value coverage for one numeric column."""

    def __init__(self, field: str = "value"):
        self.field = field

    @property
    def spec(self):
        return ComponentSpec("tabular.numeric_statistics", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "numeric", "distribution"))

    def compute(self, product, request, context):
        data = rows(product, request)
        values = finite_numbers(row.get(self.field) for row in data)
        missing = len(data) - len(values)
        return result(self.spec.name, "numeric_validity", request, product, len(values) / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"field": self.field, "missing_or_non_numeric": missing, **describe(values)}, diagnostics={"field": self.field})


class TabularOutlierRateMetric(QualityMetric):
    """Robust IQR outlier rate (Tukey fences) for a numeric field."""

    def __init__(self, field: str = "value", whisker: float = 1.5):
        self.field, self.whisker = field, float(whisker)
        if self.whisker <= 0:
            raise ValueError("whisker must be positive")

    @property
    def spec(self):
        return ComponentSpec("tabular.outlier_rate", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "robust_statistics"))

    def compute(self, product, request, context):
        data = rows(product, request)
        values = sorted(finite_numbers(row.get(self.field) for row in data))
        if len(values) < 4:
            return result(self.spec.name, "outlier_rate", request, product, 0.0, ScoreDirection.LOWER_IS_BETTER, context, statistics={"field": self.field, "numeric_count": len(values), "outlier_count": 0, "method": "iqr"})
        q1 = _quantile(values, 0.25)
        q3 = _quantile(values, 0.75)
        iqr = q3 - q1
        low, high = q1 - self.whisker * iqr, q3 + self.whisker * iqr
        outliers = [value for value in values if value < low or value > high]
        return result(self.spec.name, "outlier_rate", request, product, len(outliers) / len(values), ScoreDirection.LOWER_IS_BETTER, context, statistics={"field": self.field, "numeric_count": len(values), "outlier_count": len(outliers), "q1": q1, "q3": q3, "lower_fence": low, "upper_fence": high, "method": "iqr"}, evidence_items=({"value": value} for value in outliers))


class TabularLabelBalanceMetric(QualityMetric):
    """Normalized Shannon entropy and majority-class dominance."""

    def __init__(self, label_field: str = "label"):
        self.label_field = label_field

    @property
    def spec(self):
        return ComponentSpec("tabular.label_balance", "1.0.0", "data_eval", "quality_metric", capabilities=("tabular", "classification"))

    def compute(self, product, request, context):
        data = rows(product, request)
        labels = [row.get(self.label_field) for row in data if row.get(self.label_field) is not None]
        counts = Counter(map(str, labels))
        total = len(labels)
        entropy = -sum((count / total) * math.log(count / total) for count in counts.values()) if total else 0.0
        normalized = entropy / math.log(len(counts)) if len(counts) > 1 else (1.0 if total else 0.0)
        majority = max(counts.values()) / total if total else 0.0
        return result(self.spec.name, "label_balance", request, product, clamp(normalized), ScoreDirection.HIGHER_IS_BETTER, context, statistics={"label_field": self.label_field, "label_count": total, "class_count": len(counts), "class_counts": dict(counts), "entropy": entropy, "majority_share": majority})


def _quantile(values, probability):
    index = (len(values) - 1) * probability
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (index - low)


__all__ = ["TabularLabelBalanceMetric", "TabularNumericStatisticsMetric", "TabularOutlierRateMetric", "TabularSchemaConsistencyMetric"]
