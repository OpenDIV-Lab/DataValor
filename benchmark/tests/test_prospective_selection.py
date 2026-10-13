from __future__ import annotations

from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.prospective_selection import run_prospective_selection


def _row(
    wave: str,
    track: str,
    method: str,
    block: str,
    value: float,
    *,
    qualified: bool = True,
) -> BenchmarkResult:
    metric = {
        "valuation": "replication_owner_rank_change",
        "procurement": "oracle_ratio",
        "trading": "gain_from_trade_ratio",
    }[track]
    metrics: dict[str, MetricValue] = {metric: MetricValue(value)}
    if track == "procurement":
        metrics.update(
            {
                "budget_violation": MetricValue(not qualified),
                "seller_ir_violation_count": MetricValue(0 if qualified else 1),
            }
        )
    elif track == "trading":
        metrics.update(
            {
                "individual_rationality": MetricValue(qualified),
                "weak_budget_balance": MetricValue(qualified),
            }
        )
    return BenchmarkResult(
        run_id=f"{wave}-{track}-{method}-{block}",
        track=track,
        method_id=method,
        case_id=f"{block}-case",
        seed=0,
        status="completed",
        metrics=metrics,
        runtime_seconds=0.0,
        metadata={"independent_block": block, "primary_metric_eligible": True},
        outcome={"kind": "valuation", "scores": {"x": 1.0}, "diagnostics": {}, "utility_calls": 1},
        schema_version="1.2",
    )


def test_selection_uses_only_v1_and_preserves_ties() -> None:
    v1 = (
        _row("v1", "valuation", "a", "one", 0.1),
        _row("v1", "valuation", "b", "one", 0.1),
        _row("v1", "valuation", "c", "one", 0.5),
    )
    v2 = (
        _row("v2", "valuation", "a", "two", 0.4),
        _row("v2", "valuation", "b", "two", 0.2),
        _row("v2", "valuation", "c", "two", 0.0),
    )

    report = run_prospective_selection(
        v1,
        v2,
        headline_methods={"valuation": ("a", "b", "c")},
    )

    decision = report.decisions["valuation"]
    assert decision.selected_method_ids == ("a", "b")
    assert decision.source_wave == "v1"
    assert {row.method_id for row in report.evaluations} == {"a", "b"}
    assert {row.v2_best_method_ids for row in report.evaluations} == {("c",)}
    assert {row.method_id: row.regret for row in report.evaluations} == {
        "a": 0.4,
        "b": 0.2,
    }


def test_higher_is_better_and_qualification_loss_is_explicit() -> None:
    v1 = (
        _row("v1", "procurement", "good", "one", 0.9),
        _row("v1", "procurement", "other", "one", 0.8),
    )
    v2 = (
        _row("v2", "procurement", "good", "two", 0.95, qualified=False),
        _row("v2", "procurement", "other", "two", 0.7),
    )

    report = run_prospective_selection(
        v1,
        v2,
        headline_methods={"procurement": ("good", "other")},
    )

    assert report.decisions["procurement"].selected_method_ids == ("good",)
    evaluation = report.evaluations[0]
    assert evaluation.qualification_preserved is False
    assert evaluation.v2_score == 0.95
    assert evaluation.regret is None
    assert evaluation.status == "qualification_lost"


def test_raw_constraint_aware_and_robust_policies_can_select_differently() -> None:
    v1 = (
        _row("v1", "procurement", "raw", "b1", 1.0, qualified=False),
        _row("v1", "procurement", "raw", "b2", 0.9, qualified=False),
        _row("v1", "procurement", "mean", "b1", 0.99),
        _row("v1", "procurement", "mean", "b2", 0.81),
        _row("v1", "procurement", "robust", "b1", 0.85),
        _row("v1", "procurement", "robust", "b2", 0.85),
    )
    v2 = (
        _row("v2", "procurement", "raw", "c1", 1.0, qualified=False),
        _row("v2", "procurement", "mean", "c1", 0.7),
        _row("v2", "procurement", "robust", "c1", 0.8),
    )

    report = run_prospective_selection(
        v1,
        v2,
        headline_methods={"procurement": ("raw", "mean", "robust")},
    )

    assert report.policy_decisions["raw"]["procurement"].selected_method_ids == ("raw",)
    assert report.policy_decisions["constraint_aware"]["procurement"].selected_method_ids == ("mean",)
    assert report.policy_decisions["robust"]["procurement"].selected_method_ids == ("robust",)
    assert {row.policy for row in report.policy_evaluations} == {
        "raw",
        "constraint_aware",
        "robust",
    }
    raw_eval = next(row for row in report.policy_evaluations if row.policy == "raw")
    assert raw_eval.status == "qualification_lost"
    assert raw_eval.regret == 0.0


def test_policy_specific_selection_retains_all_ties() -> None:
    v1 = (
        _row("v1", "trading", "a", "b1", 0.8),
        _row("v1", "trading", "b", "b1", 0.8),
    )
    v2 = (
        _row("v2", "trading", "a", "b2", 0.7),
        _row("v2", "trading", "b", "b2", 0.7),
    )
    report = run_prospective_selection(
        v1,
        v2,
        headline_methods={"trading": ("a", "b")},
    )

    for policy in ("raw", "constraint_aware", "robust"):
        assert report.policy_decisions[policy]["trading"].selected_method_ids == ("a", "b")
