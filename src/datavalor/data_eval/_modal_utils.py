"""Small helpers shared by modality-specific DataEval metrics."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from statistics import mean, median, pstdev
from typing import Any

from datavalor.core import DataProduct, Evidence, RunContext

from .models import EvaluationRequest, MetricResult, ScoreDirection
from .operators import _records


def rows(product: DataProduct, request: EvaluationRequest) -> list[dict[str, Any]]:
    return _records(product, request)


def number(value: Any, default: float | None = None) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def evidence(metric: str, values: Iterable[Mapping[str, Any]], limit: int = 100) -> tuple[Evidence, ...]:
    return tuple(
        Evidence(metric, summary=str(dict(item)), metadata=dict(item))
        for item in list(values)[:limit]
    )


def result(
    metric: str,
    dimension: str,
    request: EvaluationRequest,
    product: DataProduct,
    value: float | None,
    direction: ScoreDirection,
    context: RunContext,
    *,
    unit: str | None = "ratio",
    statistics: Mapping[str, Any] | None = None,
    evidence_items: Iterable[Mapping[str, Any]] = (),
    diagnostics: Mapping[str, Any] | None = None,
) -> MetricResult:
    return MetricResult(
        metric,
        dimension,
        request.scope,
        value,
        direction,
        unit=unit,
        target_id=product.product_id,
        statistics=dict(statistics or {}),
        evidence=evidence(metric, evidence_items),
        diagnostics={"run_id": context.run_id, **dict(diagnostics or {})},
    )


def finite_numbers(values: Iterable[Any]) -> list[float]:
    return [converted for value in values if (converted := number(value)) is not None]


def describe(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "std": pstdev(values),
        "min": min(values),
        "max": max(values),
    }


__all__ = [
    "clamp",
    "describe",
    "evidence",
    "finite_numbers",
    "number",
    "result",
    "rows",
]
