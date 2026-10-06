"""Pre-registered statistical analysis for ELR-VRDS validation runs."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Iterable

import numpy as np
from scipy.stats import wilcoxon

from .metrics import MetricValue
from .models import BenchmarkResult
from .statistics import cliffs_delta, geometric_mean, holm_adjust

ELR_METHOD_ID = "elr_residual_leverage"
ELR_METHOD_IDS = (ELR_METHOD_ID, "shapley_exact_low_residual")


@dataclass(frozen=True)
class CellComparison:
    setting_id: str
    budget: float
    elr_method_id: str
    baseline_id: str
    paired_count: int
    median_elr: float
    median_baseline: float
    relative_improvement: float
    ci95_low: float
    ci95_high: float
    p_value: float
    adjusted_p_value: float
    cliffs_delta: float
    outcome: str
    modality: str
    model_family: str
    fidelity_mechanism: str


@dataclass(frozen=True)
class LossDisclosure:
    setting_id: str
    budget: float
    relative_loss: float
    residual_efficiency: float | None
    explanation: str


@dataclass(frozen=True)
class ValidationCriterion:
    criterion: int
    passed: bool
    evidence: str


@dataclass(frozen=True)
class ElrAnalysis:
    cells: tuple[CellComparison, ...]
    losses: tuple[LossDisclosure, ...]
    geometric_mean_elr: float
    geometric_mean_baseline: float
    geometric_mean_improvement: float
    criteria: tuple[ValidationCriterion, ...]
    declared_cells: tuple[str, ...]
    declared_budgets: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _number(result: BenchmarkResult, metric_id: str) -> float | None:
    if result.status != "completed":
        return None
    metric = result.metrics.get(metric_id)
    if isinstance(metric, MetricValue):
        if not metric.applicable:
            return None
        metric = metric.value
    try:
        value = float(metric)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _bootstrap_median(values: np.ndarray, samples: int, key: str) -> tuple[float, float]:
    if samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(samples, len(values)))
    medians = np.median(values[indices], axis=1)
    low, high = np.quantile(medians, (0.025, 0.975))
    return float(low), float(high)


def _paired_groups(
    results: Iterable[BenchmarkResult], metric_id: str
) -> dict[tuple[str, float], dict[str, dict[int, float]]]:
    groups: dict[tuple[str, float], dict[str, dict[int, float]]] = {}
    for result in results:
        metadata = result.metadata
        if not metadata.get("primary_task", False):
            continue
        if metadata.get("estimand", "ordinary_shapley") != "ordinary_shapley":
            continue
        value = _number(result, metric_id)
        if value is None:
            continue
        setting = str(metadata.get("setting_id", result.case_id))
        budget = float(metadata.get("budget", 0.0))
        groups.setdefault((setting, budget), {}).setdefault(result.method_id, {})[
            result.seed
        ] = value
    return groups


def _market_gain(
    results: tuple[BenchmarkResult, ...], cells: tuple[CellComparison, ...]
) -> bool:
    directions = {
        "allocation_regret": "less",
        "payment_mae": "less",
        "valuation_buyer_utility": "greater",
    }
    tests: list[float] = []
    improvements: list[bool] = []
    for metric_id, alternative in directions.items():
        groups = _paired_groups(results, metric_id)
        for cell in cells:
            methods = groups.get((cell.setting_id, cell.budget), {})
            left = methods.get(cell.elr_method_id, {})
            right = methods.get(cell.baseline_id, {})
            seeds = sorted(set(left).intersection(right))
            if len(seeds) < 5:
                continue
            elr = np.asarray([left[seed] for seed in seeds])
            baseline = np.asarray([right[seed] for seed in seeds])
            if np.allclose(elr, baseline):
                tests.append(1.0)
                improvements.append(False)
            else:
                tests.append(float(wilcoxon(elr, baseline, alternative=alternative).pvalue))
                improvements.append(
                    float(np.median(elr)) < float(np.median(baseline))
                    if alternative == "less"
                    else float(np.median(elr)) > float(np.median(baseline))
                )
    return any(p < 0.05 and gain for p, gain in zip(holm_adjust(tests), improvements, strict=True))


def analyze_elr_results(
    results: Iterable[BenchmarkResult],
    *,
    declared_cells: Iterable[str],
    declared_budgets: Iterable[float],
    bootstrap_samples: int = 10_000,
) -> ElrAnalysis:
    materialized = tuple(results)
    declared_cell_tuple = tuple(str(item) for item in declared_cells)
    declared_budget_tuple = tuple(float(item) for item in declared_budgets)
    groups = _paired_groups(materialized, "score_mae")
    comparisons: list[CellComparison] = []
    raw_p_values: list[float] = []
    for (setting, budget), methods in sorted(groups.items()):
        elr_method_id = next((method for method in ELR_METHOD_IDS if method in methods), None)
        elr_values = methods.get(elr_method_id) if elr_method_id is not None else None
        if not elr_values:
            continue
        baselines = {
            method: values for method, values in methods.items() if method not in ELR_METHOD_IDS
        }
        if not baselines:
            continue
        baseline_id = min(
            baselines,
            key=lambda method: (np.median(tuple(baselines[method].values())), method),
        )
        common = sorted(set(elr_values).intersection(baselines[baseline_id]))
        if not common:
            continue
        elr = np.asarray([elr_values[seed] for seed in common], dtype=float)
        baseline = np.asarray([baselines[baseline_id][seed] for seed in common], dtype=float)
        median_elr = float(np.median(elr))
        median_baseline = float(np.median(baseline))
        improvement = (median_baseline - median_elr) / max(abs(median_baseline), 1e-12)
        paired_improvements = (baseline - elr) / np.maximum(np.abs(baseline), 1e-12)
        low, high = _bootstrap_median(
            paired_improvements, bootstrap_samples, f"{setting}|{budget}|{baseline_id}"
        )
        p_value = (
            1.0
            if np.allclose(elr, baseline)
            else float(wilcoxon(elr, baseline, alternative="less").pvalue)
        )
        raw_p_values.append(p_value)
        metadata = next(
            result.metadata
            for result in materialized
            if str(result.metadata.get("setting_id", result.case_id)) == setting
        )
        outcome = "win" if improvement > 1e-12 else "loss" if improvement < -1e-12 else "tie"
        comparisons.append(
            CellComparison(
                setting,
                budget,
                elr_method_id,
                baseline_id,
                len(common),
                median_elr,
                median_baseline,
                improvement,
                low,
                high,
                p_value,
                1.0,
                cliffs_delta(elr, baseline),
                outcome,
                str(metadata.get("modality", "unknown")),
                str(metadata.get("model_family", "unknown")),
                str(metadata.get("fidelity_mechanism", "unknown")),
            )
        )
    adjusted = holm_adjust(raw_p_values)
    comparisons = [
        replace(item, adjusted_p_value=value)
        for item, value in zip(comparisons, adjusted, strict=True)
    ]
    cells = tuple(comparisons)
    geometric_elr = geometric_mean(item.median_elr for item in cells)
    geometric_baseline = geometric_mean(item.median_baseline for item in cells)
    geometric_improvement = 1.0 - geometric_elr / geometric_baseline

    losses = []
    for item in cells:
        if item.relative_improvement >= -0.10:
            continue
        residual_values = [
            float(result.metadata["residual_efficiency"])
            for result in materialized
            if str(result.metadata.get("setting_id", result.case_id)) == item.setting_id
            and "residual_efficiency" in result.metadata
        ]
        residual = float(np.median(residual_values)) if residual_values else None
        explanation = (
            "inefficient_residual_proxy"
            if residual is not None and residual >= 1.0
            else "unexplained_failure"
        )
        losses.append(
            LossDisclosure(
                item.setting_id,
                item.budget,
                -item.relative_improvement,
                residual,
                explanation,
            )
        )
    expected = {
        (cell, budget) for cell in declared_cell_tuple for budget in declared_budget_tuple
    }
    observed = {(item.setting_id, item.budget) for item in cells}
    significant = [
        item
        for item in cells
        if item.outcome == "win" and item.adjusted_p_value < 0.05
    ]
    win_rate = sum(item.outcome == "win" for item in cells) / max(1, len(cells))
    dimensions = (
        len({item.model_family for item in significant}),
        len({item.modality for item in significant}),
        len({item.fidelity_mechanism for item in significant}),
    )
    market_gain = _market_gain(materialized, cells)
    criteria = (
        ValidationCriterion(1, win_rate >= 0.75, f"cell win rate={win_rate:.1%}"),
        ValidationCriterion(
            2,
            geometric_improvement >= 0.20,
            f"geometric-mean MAE improvement={geometric_improvement:.1%}",
        ),
        ValidationCriterion(
            3,
            all(count >= 2 for count in dimensions),
            "significant-gain coverage model/modality/fidelity=" + "/".join(map(str, dimensions)),
        ),
        ValidationCriterion(4, market_gain, f"significant downstream gain={market_gain}"),
        ValidationCriterion(
            5,
            expected <= observed and all(loss.explanation != "unexplained_failure" for loss in losses),
            f"declared cells covered={len(expected & observed)}/{len(expected)}; >10% losses={len(losses)}",
        ),
        ValidationCriterion(
            6,
            expected <= observed,
            f"declared cell-budget coverage={len(expected & observed)}/{len(expected)}",
        ),
    )
    return ElrAnalysis(
        cells,
        tuple(losses),
        geometric_elr,
        geometric_baseline,
        geometric_improvement,
        criteria,
        declared_cell_tuple,
        declared_budget_tuple,
    )


__all__ = [
    "CellComparison",
    "ELR_METHOD_ID",
    "ELR_METHOD_IDS",
    "ElrAnalysis",
    "LossDisclosure",
    "ValidationCriterion",
    "analyze_elr_results",
    "cliffs_delta",
    "holm_adjust",
]
