"""Dependency-light evaluation operators migrated into DataEval semantics."""

from __future__ import annotations

from typing import Any, Iterable

from datavalor.core import ComponentSpec, DataProduct, RunContext

from .interfaces import QualityMetric
from .models import EvaluationRequest, MetricResult, ScoreDirection


def _records(product: DataProduct, request: EvaluationRequest) -> list[dict[str, Any]]:
    supplied = request.options.get("records")
    if supplied is not None:
        return [dict(row) for row in supplied]
    try:
        from datavalor.data_gov.data_product import adapter_from_uri

        return adapter_from_uri(product.data.uri).materialize()
    except (ValueError, FileNotFoundError):
        return []


class LexicalDiversityMetric(QualityMetric):
    """Type-token diversity with coverage smoothing for text records."""

    def __init__(self, text_field: str = "text", min_tokens: int = 1):
        self.text_field, self.min_tokens = text_field, min_tokens

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("text.lexical_diversity", "1.0", "data_eval", "quality_metric", capabilities=("text",))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = _records(product, request); tokens: list[str] = []; valid = 0
        for row in rows:
            current = [token.lower() for token in str(row.get(self.text_field, "")).split() if token.strip()]
            if len(current) >= self.min_tokens:
                valid += 1; tokens.extend(current)
        ratio = len(set(tokens)) / len(tokens) if tokens else 0.0
        score = max(0.0, min(1.0, ratio * 0.7 + valid / max(1, len(rows)) * 0.3))
        return MetricResult(self.spec.name, "diversity", request.scope, score, ScoreDirection.HIGHER_IS_BETTER,
                            unit="ratio", target_id=product.product_id,
                            statistics={"record_count": len(rows), "token_count": len(tokens), "unique_tokens": len(set(tokens))},
                            diagnostics={"run_id": context.run_id})


class FieldSummaryMetric(QualityMetric):
    """Expose missingness, cardinality and simple numeric statistics as quality evidence."""

    def __init__(self, field: str): self.field = field

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("field.summary", "1.0", "data_prof", "quality_metric", capabilities=("dataset", "field"))

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = _records(product, request); values = [row.get(self.field) for row in rows]; present = [v for v in values if v is not None]
        numeric = [float(v) for v in present if isinstance(v, (int, float)) and not isinstance(v, bool)]
        stats = {"record_count": len(rows), "missing_count": len(values) - len(present), "distinct_count": len(set(map(str, present)))}
        if numeric: stats.update(min=min(numeric), max=max(numeric), mean=sum(numeric) / len(numeric))
        return MetricResult(self.spec.name, "field_summary", request.scope, None, ScoreDirection.DESCRIPTIVE,
                            target_id=product.product_id, statistics=stats, diagnostics={"field": self.field, "run_id": context.run_id})


def lexical_diversity(records: Iterable[dict[str, Any]], text_field: str = "text", min_tokens: int = 1) -> float:
    rows = list(records); tokens = [token.lower() for row in rows for token in str(row.get(text_field, "")).split() if token.strip()]
    valid = sum(len(str(row.get(text_field, "")).split()) >= min_tokens for row in rows)
    ratio = len(set(tokens)) / len(tokens) if tokens else 0.0
    return max(0.0, min(1.0, ratio * .7 + valid / max(1, len(rows)) * .3))


__all__ = ["FieldSummaryMetric", "LexicalDiversityMetric", "lexical_diversity"]
