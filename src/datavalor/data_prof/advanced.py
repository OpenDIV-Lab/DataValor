"""Additional dependency-free profiling algorithms.

These components produce descriptive facts.  They deliberately do not turn a
statistic into a quality score; policy and task-specific interpretation stay
in DataEval/DataGov.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from datavalor.core import ComponentSpec, DataProduct, RunContext

from .builtins import _numeric, records_for
from .interfaces import ProfileMetric
from .models import ProfileRequest


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _entropy(probabilities: Iterable[float]) -> float:
    return -sum(probability * math.log(probability, 2) for probability in probabilities if probability > 0)


class RobustStatisticsMetric(ProfileMetric):
    """Quantiles, spread, coefficient of variation and robust outlier fences."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("advanced.robust_statistics", "1.0.0", "data_prof", "profile_metric", capabilities=("numeric", "quantiles", "robust"))

    def measure(self, product: DataProduct, field: str | None, context: RunContext) -> Mapping[str, Any]:
        if field is None:
            raise ValueError("RobustStatisticsMetric requires a field")
        values = _numeric(row.get(field) for row in records_for(product, ProfileRequest(options=context.config)))
        if not values:
            return {"field": field, "count": 0, "statistics": {}, "diagnostics": {"reason": "no finite numeric values"}}
        q01, q05, q25, q50, q75, q95, q99 = (_quantile(values, p) for p in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99))
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        std = math.sqrt(variance)
        iqr = q75 - q25
        lower, upper = q25 - 1.5 * iqr, q75 + 1.5 * iqr
        return {"field": field, "count": len(values), "statistics": {"q01": q01, "q05": q05, "q25": q25, "q50": q50, "q75": q75, "q95": q95, "q99": q99, "median": q50, "variance": variance, "std": std, "iqr": iqr, "coefficient_of_variation": std / abs(mean) if mean else None, "lower_fence": lower, "upper_fence": upper, "outlier_count": sum(value < lower or value > upper for value in values)}, "diagnostics": {"run_id": context.run_id}}


class CategoricalConcentrationMetric(ProfileMetric):
    """Cardinality, entropy, Gini concentration and top-k coverage."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("advanced.categorical_concentration", "1.0.0", "data_prof", "profile_metric", capabilities=("categorical", "entropy", "concentration"))

    def measure(self, product: DataProduct, field: str | None, context: RunContext) -> Mapping[str, Any]:
        if field is None:
            raise ValueError("CategoricalConcentrationMetric requires a field")
        values = [str(row[field]) for row in records_for(product, ProfileRequest(options=context.config)) if row.get(field) is not None]
        counts = Counter(values)
        total = len(values)
        probabilities = [count / total for count in counts.values()] if total else []
        top = counts.most_common(10)
        return {"field": field, "count": total, "statistics": {"distinct_count": len(counts), "cardinality_ratio": len(counts) / total if total else None, "entropy_bits": _entropy(probabilities), "max_entropy_bits": math.log(len(counts), 2) if len(counts) > 1 else 0.0, "gini_concentration": sum(probability**2 for probability in probabilities), "top_k": [{"value": value, "count": count, "share": count / total} for value, count in top], "top_10_coverage": sum(count for _, count in top) / total if total else 0.0}, "diagnostics": {"run_id": context.run_id}}


class PairwiseCorrelationMetric(ProfileMetric):
    """Pearson correlation and sample covariance for two numeric fields."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("advanced.pairwise_correlation", "1.0.0", "data_prof", "profile_metric", capabilities=("numeric", "correlation"))

    def measure(self, product: DataProduct, field: str | None, context: RunContext) -> Mapping[str, Any]:
        if not field or "," not in field:
            raise ValueError("PairwiseCorrelationMetric field must be 'left,right'")
        left_name, right_name = (item.strip() for item in field.split(",", 1))
        pairs = [(float(row[left_name]), float(row[right_name])) for row in records_for(product, ProfileRequest(options=context.config)) if isinstance(row.get(left_name), (int, float)) and not isinstance(row.get(left_name), bool) and isinstance(row.get(right_name), (int, float)) and not isinstance(row.get(right_name), bool) and math.isfinite(float(row[left_name])) and math.isfinite(float(row[right_name]))]
        if len(pairs) < 2:
            return {"field": field, "count": len(pairs), "statistics": {"pearson_r": None, "covariance": None}, "diagnostics": {"reason": "at least two finite pairs are required"}}
        xs, ys = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
        mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
        cross = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        var_x = sum((x - mean_x) ** 2 for x in xs)
        var_y = sum((y - mean_y) ** 2 for y in ys)
        return {"field": field, "count": len(pairs), "statistics": {"pearson_r": cross / math.sqrt(var_x * var_y) if var_x and var_y else None, "covariance": cross / (len(pairs) - 1), "variance_left": var_x / (len(pairs) - 1), "variance_right": var_y / (len(pairs) - 1)}, "diagnostics": {"run_id": context.run_id}}


def stratified_sample(records: Iterable[Mapping[str, Any]], strata_fields: Sequence[str], sample_size: int, seed: int = 0) -> list[dict[str, Any]]:
    """Return a deterministic proportional stratified sample.

    Every stratum receives at least one row when the requested sample is large
    enough; remaining slots are allocated by largest remainder.
    """
    rows = [dict(row) for row in records]
    if sample_size <= 0 or not rows:
        return []
    if not strata_fields:
        rng = random.Random(seed); rng.shuffle(rows); return rows[:sample_size]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row.get(field, "<missing>")) for field in strata_fields)].append(row)
    target = min(sample_size, len(rows)); allocation: dict[tuple[str, ...], int] = {}
    remainders: list[tuple[float, tuple[str, ...]]] = []
    for key, group in groups.items():
        exact = target * len(group) / len(rows)
        allocation[key] = min(len(group), max(1, math.floor(exact))) if target >= len(groups) else 0
        remainders.append((exact - math.floor(exact), key))
    while sum(allocation.values()) < target:
        for _, key in sorted(remainders, key=lambda item: (-item[0], item[1])):
            if sum(allocation.values()) >= target:
                break
            if allocation[key] < len(groups[key]):
                allocation[key] += 1
    rng = random.Random(seed); result: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key][:]; rng.shuffle(group); result.extend(group[: allocation[key]])
    rng.shuffle(result)
    return result[:target]


@dataclass(frozen=True)
class DriftFieldResult:
    field: str
    method: str
    statistic: float | None
    threshold: float
    drifted: bool
    reference_count: int
    current_count: int
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriftReport:
    reference_product_id: str
    current_product_id: str
    fields: tuple[DriftFieldResult, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)


def _psi(reference: list[float], current: list[float], bins: int = 10) -> tuple[float, list[Mapping[str, Any]]]:
    if not reference or not current:
        return None, []
    cuts = sorted({_quantile(reference, index / bins) for index in range(1, bins)})
    def bucket(value: float) -> int:
        return sum(value > cut for cut in cuts)
    ref_count, cur_count = Counter(bucket(x) for x in reference), Counter(bucket(x) for x in current)
    total_ref, total_cur = len(reference), len(current); value = 0.0; detail = []
    for index in range(len(cuts) + 1):
        p = max(ref_count[index] / total_ref, 1e-6); q = max(cur_count[index] / total_cur, 1e-6)
        contribution = (q - p) * math.log(q / p); value += contribution
        detail.append({"bin": index, "reference_share": p, "current_share": q, "contribution": contribution})
    return value, detail


def _js(reference: list[str], current: list[str]) -> float | None:
    if not reference or not current:
        return None
    ref, cur = Counter(reference), Counter(current); keys = set(ref) | set(cur); n, m = len(reference), len(current)
    value = 0.0
    for key in keys:
        p, q = ref[key] / n, cur[key] / m; midpoint = (p + q) / 2
        if p: value += 0.5 * p * math.log(p / midpoint, 2)
        if q: value += 0.5 * q * math.log(q / midpoint, 2)
    return value


class DriftAnalyzer:
    """Compare two record snapshots using PSI (numeric) and JS divergence."""

    def analyze(self, reference: DataProduct, current: DataProduct, context: RunContext, fields: Sequence[str] = (), psi_threshold: float = 0.2, js_threshold: float = 0.1) -> DriftReport:
        ref_input = context.config.get("reference_records")
        cur_input = context.config.get("current_records")
        ref_rows = records_for(reference, ProfileRequest(options={"records": ref_input})) if ref_input is not None else records_for(reference, ProfileRequest(options=context.config))
        cur_rows = records_for(current, ProfileRequest(options={"records": cur_input})) if cur_input is not None else records_for(current, ProfileRequest(options=context.config))
        names = list(fields) or sorted({str(key) for row in ref_rows + cur_rows for key in row})
        results: list[DriftFieldResult] = []
        for name in names:
            ref_values, cur_values = [row.get(name) for row in ref_rows], [row.get(name) for row in cur_rows]
            if any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in ref_values + cur_values):
                a, b = _numeric(ref_values), _numeric(cur_values); statistic, details = _psi(a, b)
                results.append(DriftFieldResult(name, "psi", statistic, psi_threshold, statistic is not None and statistic >= psi_threshold, len(a), len(b), {"bins": details}))
            else:
                a, b = [str(value) for value in ref_values if value is not None], [str(value) for value in cur_values if value is not None]; statistic = _js(a, b)
                results.append(DriftFieldResult(name, "jensen_shannon", statistic, js_threshold, statistic is not None and statistic >= js_threshold, len(a), len(b)))
        drifted = sum(result.drifted for result in results)
        return DriftReport(reference.product_id, current.product_id, tuple(results), {"field_count": len(results), "drifted_field_count": drifted, "drift_rate": drifted / len(results) if results else 0.0, "run_id": context.run_id})


__all__ = ["RobustStatisticsMetric", "CategoricalConcentrationMetric", "PairwiseCorrelationMetric", "stratified_sample", "DriftFieldResult", "DriftReport", "DriftAnalyzer"]
