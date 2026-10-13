from __future__ import annotations

import math

from datamechbench.elr_analysis import analyze_elr_results, cliffs_delta, holm_adjust
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult


def _rows() -> tuple[BenchmarkResult, ...]:
    rows = []
    cells = (
        ("tab-rf", "tabular", "tree_ensemble", "ensemble_width", 0.50, 1.00),
        ("tab-gb", "tabular", "boosting", "boosting_round_prefix", 0.55, 1.00),
        ("image-head", "image", "neural_head", "training_epoch_prefix", 0.45, 1.00),
        ("text-head", "text", "neural_head", "training_epoch_prefix", 1.20, 1.00),
    )
    for cell, modality, family, fidelity, elr, baseline in cells:
        for budget in (64, 128):
            for seed in range(10):
                metadata = {
                    "setting_id": cell,
                    "budget": budget,
                    "primary_task": True,
                    "split": "confirmatory",
                    "estimand": "ordinary_shapley",
                    "modality": modality,
                    "model_family": family,
                    "fidelity_mechanism": fidelity,
                    "residual_efficiency": 0.2 if cell != "text-head" else 1.4,
                }
                rows.append(
                    BenchmarkResult(
                        f"elr-{cell}-{budget}-{seed}",
                        "valuation",
                        "shapley_exact_low_residual",
                        cell,
                        seed,
                        "completed",
                        {
                            "score_mae": MetricValue(elr),
                            "allocation_regret": MetricValue(elr / 10),
                        },
                        0.1,
                        metadata=metadata,
                    )
                )
                rows.append(
                    BenchmarkResult(
                        f"base-{cell}-{budget}-{seed}",
                        "valuation",
                        "shapiq_svarm",
                        cell,
                        seed,
                        "completed",
                        {
                            "score_mae": MetricValue(baseline),
                            "allocation_regret": MetricValue(baseline / 10),
                        },
                        0.1,
                        metadata=metadata,
                    )
                )
    return tuple(rows)


def test_effect_size_and_holm_are_pinned() -> None:
    assert cliffs_delta([1, 1, 1], [2, 2, 2]) == -1.0
    assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]


def test_analysis_reports_paired_cells_geomean_and_losses() -> None:
    analysis = analyze_elr_results(
        _rows(),
        declared_cells=("tab-rf", "tab-gb", "image-head", "text-head"),
        declared_budgets=(64, 128),
        bootstrap_samples=500,
    )
    assert len(analysis.cells) == 8
    assert all(cell.paired_count == 10 for cell in analysis.cells)
    assert sum(cell.outcome == "win" for cell in analysis.cells) == 6
    assert sum(cell.outcome == "loss" for cell in analysis.cells) == 2
    assert all(cell.cliffs_delta == -1.0 for cell in analysis.cells[:6])
    assert math.isclose(analysis.geometric_mean_elr, (0.5 * 0.55 * 0.45 * 1.2) ** 0.25)
    assert analysis.losses and all(loss.explanation == "inefficient_residual_proxy" for loss in analysis.losses)
    assert len(analysis.criteria) == 6
    assert analysis.criteria[0].passed
    assert analysis.criteria[1].passed
    assert analysis.criteria[4].passed
    assert analysis.criteria[5].passed

