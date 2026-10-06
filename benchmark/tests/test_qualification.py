from __future__ import annotations

from dataclasses import replace

from datamechbench.leaderboard import LeaderboardRow
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.qualification import (
    attach_constraint_ranks,
    summarize_constraint_profiles,
)


def _result(
    method: str,
    case: str,
    metrics: dict[str, MetricValue],
    *,
    track: str = "procurement",
    setting: str = "P-ADDITIVE",
    capabilities: tuple[str, ...] = ("payments", "strategic_reports"),
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"{method}-{case}",
        track=track,
        method_id=method,
        case_id=case,
        seed=0,
        status="completed",
        metrics=metrics,
        runtime_seconds=0.1,
        metadata={
            "method_family": method,
            "implementation_kind": "native",
            "benchmark_setting": setting,
            "method_capabilities": list(capabilities),
        },
    )


def _procurement_metrics(*, budget=0, ir=0, deviation=0.0):
    return {
        "budget_violation": MetricValue(budget),
        "seller_ir_violation_count": MetricValue(ir),
        "max_deviation_gain": MetricValue(deviation),
    }


def test_constraint_profiles_distinguish_pass_fail_and_not_auditable() -> None:
    rows = [
        _result("pass", "c1", _procurement_metrics()),
        _result("pass", "c2", _procurement_metrics()),
        _result("fail", "c1", _procurement_metrics(budget=1)),
        _result("fail", "c2", _procurement_metrics(ir=2, deviation=0.4)),
        _result("unknown", "c1", _procurement_metrics()),
        _result(
            "unknown",
            "c2",
            {**_procurement_metrics(), "budget_violation": MetricValue.na("missing_payments")},
        ),
    ]

    profiles = {
        profile.family_id: profile for profile in summarize_constraint_profiles(rows)
    }

    assert profiles["pass"].constraint_status == "pass"
    assert profiles["fail"].constraint_status == "fail"
    assert set(profiles["fail"].failed_rules) == {
        "budget_violation",
        "seller_ir_violation_count",
        "max_deviation_gain",
    }
    assert profiles["fail"].rule_values["seller_ir_violation_count"] == 2
    assert profiles["unknown"].constraint_status == "not_auditable"
    assert profiles["unknown"].missing_rules == ("budget_violation",)


def test_capability_conditioned_rule_is_skipped_only_when_capability_absent() -> None:
    without_strategy = _result(
        "posted",
        "c1",
        {
            "budget_violation": MetricValue(0),
            "seller_ir_violation_count": MetricValue(0),
            "max_deviation_gain": MetricValue.na("strategic_reports_unsupported"),
        },
        capabilities=("payments",),
    )
    with_strategy = replace(
        without_strategy,
        run_id="truthful-c1",
        method_id="truthful",
        metadata={**without_strategy.metadata, "method_family": "truthful", "method_capabilities": ["payments", "strategic_reports"]},
    )

    profiles = {
        profile.family_id: profile
        for profile in summarize_constraint_profiles((without_strategy, with_strategy))
    }

    assert profiles["posted"].constraint_status == "pass"
    assert profiles["truthful"].constraint_status == "not_auditable"
    assert profiles["truthful"].missing_rules == ("max_deviation_gain",)


def test_valuation_without_policy_is_not_required() -> None:
    row = _result(
        "value",
        "v1",
        {"score_mae": MetricValue(0.0)},
        track="valuation",
        setting="V-AXIOM",
        capabilities=("scores",),
    )

    profile = summarize_constraint_profiles((row,))[0]

    assert profile.constraint_status == "not_required"
    assert profile.rule_values == {}


def test_constraint_rank_retains_raw_rows_and_excludes_failures() -> None:
    def leaderboard(family: str, mean: float, raw_rank: int) -> LeaderboardRow:
        return LeaderboardRow(
            "procurement", "P-ADDITIVE", "stable", family, family,
            "oracle_ratio", "maximize", mean, 0.0, mean, mean, 2, 2,
            raw_rank, 2, 1.0, raw_rank, raw_rank,
        )

    results = [
        _result("unsafe", "c1", _procurement_metrics(budget=1)),
        _result("unsafe", "c2", _procurement_metrics()),
        _result("safe", "c1", _procurement_metrics()),
        _result("safe", "c2", _procurement_metrics()),
    ]
    profiles = summarize_constraint_profiles(results)

    ranked = {
        row.family_id: row
        for row in attach_constraint_ranks(
            (leaderboard("unsafe", 0.9, 1), leaderboard("safe", 0.8, 2)),
            profiles,
        )
    }

    assert ranked["unsafe"].raw_rank == 1
    assert ranked["unsafe"].constraint_status == "fail"
    assert ranked["unsafe"].constraint_qualified_rank is None
    assert ranked["safe"].constraint_status == "pass"
    assert ranked["safe"].constraint_qualified_rank == 1
