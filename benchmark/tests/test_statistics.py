from __future__ import annotations

from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.statistics import holm_adjust, paired_comparisons


def _result(method: str, case: str, value: float, *, setting: str) -> BenchmarkResult:
    metric = "score_mae" if setting == "V-AXIOM" else "oracle_ratio"
    track = "valuation" if setting == "V-AXIOM" else "procurement"
    return BenchmarkResult(
        run_id=f"{method}-{case}", track=track, method_id=method,
        case_id=case, seed=0, status="completed",
        metrics={metric: MetricValue(value)}, runtime_seconds=0.01,
        metadata={
            "method_family": method,
            "method_role": "method",
            "implementation_kind": "native",
            "provenance_kind": "paper_exact",
            "benchmark_setting": setting,
            "pilot": False,
        },
    )


def test_paired_delta_is_positive_for_better_method_in_both_directions() -> None:
    maximize = [
        _result(method, f"c{i}", value, setting="P-ADDITIVE")
        for i in range(6)
        for method, value in (("a", 0.9), ("b", 0.7))
    ]
    minimize = [
        _result(method, f"c{i}", value, setting="V-AXIOM")
        for i in range(6)
        for method, value in (("a", 0.1), ("b", 0.3))
    ]

    max_row = paired_comparisons(maximize, "P-ADDITIVE", bootstrap_samples=500)[0]
    min_row = paired_comparisons(minimize, "V-AXIOM", bootstrap_samples=500)[0]

    for row in (max_row, min_row):
        assert (row.family_a, row.family_b) == ("a", "b")
        assert row.mean_delta == 0.2
        assert (row.wins, row.ties, row.losses) == (6, 0, 0)
        assert row.ci95_low > 0
        assert row.conclusion == "a_better"


def test_bootstrap_is_deterministic_and_holm_is_monotone() -> None:
    rows = [
        _result(method, f"c{i}", value, setting="P-ADDITIVE")
        for i in range(6)
        for method, value in (("a", 0.9 - i * 0.01), ("b", 0.6 + i * 0.01), ("c", 0.5))
    ]

    first = paired_comparisons(rows, "P-ADDITIVE", bootstrap_samples=300)
    second = paired_comparisons(rows, "P-ADDITIVE", bootstrap_samples=300)

    assert first == second
    assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]


def test_ties_and_small_cohorts_do_not_claim_significance() -> None:
    ties = [
        _result(method, f"c{i}", 0.5, setting="P-ADDITIVE")
        for i in range(6)
        for method in ("a", "b")
    ]
    small = [
        _result(method, f"c{i}", value, setting="P-ADDITIVE")
        for i in range(4)
        for method, value in (("a", 0.9), ("b", 0.1))
    ]

    tied = paired_comparisons(ties, "P-ADDITIVE", bootstrap_samples=200)[0]
    insufficient = paired_comparisons(small, "P-ADDITIVE", bootstrap_samples=200)[0]

    assert tied.conclusion == "indistinguishable"
    assert tied.p_value == tied.adjusted_p_value == 1.0
    assert insufficient.conclusion == "insufficient_cases"
    assert insufficient.p_value is None
    assert insufficient.adjusted_p_value is None


def test_nonzero_differences_with_p_value_one_are_finalized() -> None:
    deltas = (
        0.35079341896931315,
        -0.5032676040543316,
        0.15670555717554135,
        -0.10952380952380947,
        0.0981959215346816,
    )
    rows = [
        _result(method, f"c{i}", value, setting="P-ADDITIVE")
        for i, delta in enumerate(deltas)
        for method, value in (("a", delta), ("b", 0.0))
    ]

    comparison = paired_comparisons(rows, "P-ADDITIVE", bootstrap_samples=200)[0]

    assert comparison.p_value == 1.0
    assert comparison.adjusted_p_value == 1.0
    assert comparison.conclusion == "indistinguishable"
