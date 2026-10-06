"""Claim-safe statistics for paired PG-ELR paper experiments."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import spearmanr, wilcoxon

from .statistics import cliffs_delta, geometric_mean, holm_adjust


@dataclass(frozen=True)
class CellSummary:
    dataset_id: str
    partition: str
    budget: int
    method_id: str
    seed_count: int
    median_mae: float | None
    mean_mae: float | None
    status: str


@dataclass(frozen=True)
class PairedMethodComparison:
    method_id: str
    baseline_id: str
    paired_seeds: int
    mean_mae_difference: float
    ci95_low: float
    ci95_high: float
    wilcoxon_p_value: float
    cliffs_delta: float
    holm_adjusted_p_value: float | None
    outcome: str


@dataclass(frozen=True)
class DatasetLevelSummary:
    dataset_count: int
    geometric_mean_normalized_mae: float
    inference_unit: str = "dataset"


@dataclass(frozen=True)
class RoutingSummary:
    completed_cells: int
    not_applicable_cells: int
    routing_accuracy: float | None
    mean_normalized_regret: float | None
    disagreement_frequency: float | None


def score_vector_metrics(
    predicted: Sequence[float],
    truth: Sequence[float],
) -> dict[str, float]:
    predicted_values = np.asarray(predicted, dtype=float)
    truth_values = np.asarray(truth, dtype=float)
    if predicted_values.shape != truth_values.shape or predicted_values.ndim != 1:
        raise ValueError("predicted and truth must be same-length vectors")
    if not len(truth_values) or not np.all(np.isfinite(predicted_values)) or not np.all(
        np.isfinite(truth_values)
    ):
        raise ValueError("score vectors must be non-empty and finite")
    errors = predicted_values - truth_values
    denominator = float(np.mean(np.abs(truth_values)))
    order = np.argsort(-predicted_values, kind="stable")
    relevance = truth_values - min(0.0, float(np.min(truth_values)))
    discounts = np.log2(np.arange(2, len(relevance) + 2))
    dcg = float(np.sum(relevance[order] / discounts))
    ideal = float(np.sum(np.sort(relevance)[::-1] / discounts))
    correlation = spearmanr(predicted_values, truth_values).statistic
    return {
        "mae": float(np.mean(np.abs(errors))),
        "normalized_mae": (
            float(np.mean(np.abs(errors))) / denominator
            if denominator > 0
            else float(np.mean(np.abs(errors)))
        ),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "max_owner_error": float(np.max(np.abs(errors))),
        "spearman": float(correlation),
        "ndcg": dcg / ideal if ideal > 0 else 1.0,
    }


def summarize_cell(
    rows: Iterable[Mapping[str, Any]],
    *,
    dataset_id: str,
    partition: str,
    budget: int,
    method_id: str,
) -> CellSummary:
    relevant = [
        row
        for row in rows
        if str(row.get("dataset_id")) == dataset_id
        and str(row.get("partition")) == partition
        and int(row.get("budget", -1)) == budget
        and str(row.get("method_id")) == method_id
    ]
    completed = [float(row["mae"]) for row in relevant if row.get("status") == "completed"]
    if not completed:
        return CellSummary(dataset_id, partition, budget, method_id, 0, None, None, "not_applicable")
    return CellSummary(
        dataset_id,
        partition,
        budget,
        method_id,
        len(completed),
        float(np.median(completed)),
        float(np.mean(completed)),
        "completed",
    )


def paired_method_comparison(
    rows: Iterable[Mapping[str, Any]],
    *,
    method_id: str,
    baseline_id: str,
    bootstrap_samples: int = 10_000,
    tie_tolerance: float = 0.01,
) -> PairedMethodComparison:
    values: dict[str, dict[tuple[Any, ...], float]] = {method_id: {}, baseline_id: {}}
    for row in rows:
        method = str(row.get("method_id"))
        if row.get("status") != "completed" or method not in values:
            continue
        key = (
            row.get("dataset_id"),
            row.get("partition"),
            row.get("budget"),
            row.get("estimator_seed"),
        )
        values[method][key] = float(row["mae"])
    common = sorted(set(values[method_id]) & set(values[baseline_id]), key=repr)
    if not common:
        raise ValueError("paired comparison requires common completed seeds")
    method_values = np.asarray([values[method_id][key] for key in common])
    baseline_values = np.asarray([values[baseline_id][key] for key in common])
    deltas = method_values - baseline_values
    seed = int.from_bytes(
        hashlib.sha256(f"{method_id}|{baseline_id}|{common}".encode()).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(deltas), size=(bootstrap_samples, len(deltas)))
    low, high = np.quantile(np.mean(deltas[indices], axis=1), (0.025, 0.975))
    p_value = 1.0 if np.allclose(deltas, 0) else float(wilcoxon(deltas).pvalue)
    relative = (float(np.median(method_values)) - float(np.median(baseline_values))) / max(
        abs(float(np.median(baseline_values))), 1e-15
    )
    outcome = "tie" if abs(relative) < tie_tolerance else "win" if relative < 0 else "loss"
    return PairedMethodComparison(
        method_id,
        baseline_id,
        len(common),
        float(np.mean(deltas)),
        float(low),
        float(high),
        p_value,
        cliffs_delta(method_values, baseline_values),
        None,
        outcome,
    )


def holm_comparison_family(
    comparisons: Sequence[PairedMethodComparison],
) -> tuple[PairedMethodComparison, ...]:
    adjusted = holm_adjust([item.wilcoxon_p_value for item in comparisons])
    return tuple(
        replace(item, holm_adjusted_p_value=float(value))
        for item, value in zip(comparisons, adjusted, strict=True)
    )


def dataset_level_summary(
    cells: Iterable[CellSummary],
    *,
    baseline_medians: Mapping[str, float],
) -> DatasetLevelSummary:
    by_dataset: dict[str, list[float]] = {}
    for cell in cells:
        if cell.status != "completed" or cell.median_mae is None:
            continue
        baseline = float(baseline_medians[cell.dataset_id])
        if baseline <= 0:
            raise ValueError("baseline medians must be positive")
        by_dataset.setdefault(cell.dataset_id, []).append(cell.median_mae / baseline)
    dataset_ratios = [float(np.mean(values)) for values in by_dataset.values()]
    return DatasetLevelSummary(len(dataset_ratios), geometric_mean(dataset_ratios))


def routing_summary(rows: Iterable[Mapping[str, Any]]) -> RoutingSummary:
    materialized = tuple(rows)
    completed = [row for row in materialized if row.get("status") == "completed"]
    missing = sum(row.get("status") != "completed" for row in materialized)
    if not completed:
        return RoutingSummary(0, missing, None, None, None)
    accuracy = np.mean(
        [row["selected_method"] == row["oracle_method"] for row in completed]
    )
    regrets = [
        (float(row["selected_mae"]) - float(row["oracle_mae"]))
        / max(abs(float(row["oracle_mae"])), 1e-15)
        for row in completed
    ]
    disagreement = np.mean([bool(row["probe_disagreement"]) for row in completed])
    return RoutingSummary(
        len(completed), missing, float(accuracy), float(np.mean(regrets)), float(disagreement)
    )


__all__ = [
    "CellSummary",
    "DatasetLevelSummary",
    "PairedMethodComparison",
    "RoutingSummary",
    "dataset_level_summary",
    "holm_comparison_family",
    "paired_method_comparison",
    "routing_summary",
    "score_vector_metrics",
    "summarize_cell",
]
