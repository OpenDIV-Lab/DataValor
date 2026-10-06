from __future__ import annotations

from datamechbench.confirmatory import (
    ContrastSpec,
    analyze_confirmatory_contrasts,
    quantify_representativeness,
)
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult


def _row(case: str, block: str, method: str, seed: int, value: float) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"{case}-{method}-{seed}",
        track="valuation",
        method_id=method,
        case_id=case,
        seed=seed,
        status="completed",
        metrics={"score": MetricValue(value)},
        runtime_seconds=0.0,
        metadata={"independent_block": block, "benchmark_setting": "V-HOLDOUT"},
    )


def test_seed_and_case_repetition_do_not_inflate_block_inference_unit() -> None:
    rows = []
    for block, delta in (("block-a", 0.3), ("block-b", 0.2), ("block-c", 0.1)):
        for case_index in range(4):
            case = f"{block}-case-{case_index}"
            for seed in range(10):
                rows.append(_row(case, block, "a", seed, 0.5 + delta))
                rows.append(_row(case, block, "b", seed, 0.5))
    spec = ContrastSpec(
        contrast_id="primary",
        track="valuation",
        method_a="a",
        method_b="b",
        metric="score",
        direction="higher",
        estimand="mean_oriented_difference",
        inference_unit="independent_block",
        ci_method="percentile_block_bootstrap",
        multiplicity_family="valuation",
    )

    [result] = analyze_confirmatory_contrasts(rows, (spec,), bootstrap_samples=2000)

    assert result.independent_blocks == 3
    assert result.case_count == 12
    assert result.run_count == 240
    assert abs(result.effect - 0.2) < 1e-12
    assert result.ci_low > 0
    assert result.decision == "confirmed"


def test_missing_method_in_one_block_is_not_auditable() -> None:
    rows = [
        _row("a1", "block-a", "a", 0, 0.8),
        _row("a1", "block-a", "b", 0, 0.5),
        _row("b1", "block-b", "a", 0, 0.7),
    ]
    spec = ContrastSpec(
        "primary", "valuation", "a", "b", "score", "higher",
        "mean_oriented_difference", "independent_block",
        "percentile_block_bootstrap", "valuation",
    )

    [result] = analyze_confirmatory_contrasts(rows, (spec,), bootstrap_samples=200)

    assert result.decision == "not_auditable"
    assert result.missing_blocks == ("block-b",)


def test_representativeness_reports_separate_distances_and_support() -> None:
    metrics = quantify_representativeness(
        development=[0.0, 0.2, 0.4, 0.6, 0.8],
        heldout=[0.1, 0.3, 0.5, 0.7, 1.2],
        bins=5,
    )

    assert set(metrics) == {
        "wasserstein_distance",
        "jensen_shannon_divergence",
        "heldout_outside_development_fraction",
        "source_coverage",
    }
    assert metrics["wasserstein_distance"] > 0
    assert metrics["jensen_shannon_divergence"] >= 0
    assert metrics["heldout_outside_development_fraction"] == 0.2
    assert metrics["source_coverage"] == 1.0
    assert "composite" not in metrics
