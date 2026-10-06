from __future__ import annotations

import pytest
from datamechbench.deep_dives import (
    claim_aggregation_rows,
    market_thickness_rows,
    procurement_auditability_rows,
    replication_decomposition_rows,
)
from datamechbench.expectations import ExpectationSpec
from datamechbench.leaderboard import LeaderboardRow
from datamechbench.models import BenchmarkResult


def _leaderboard(
    family: str,
    mean: float,
    *,
    rank: int,
    status: str,
    constraint_rank: int | None,
    reason: str = "",
) -> LeaderboardRow:
    return LeaderboardRow(
        track="procurement",
        setting="P-TEST",
        scope="stable",
        family_id=family,
        method_id=family,
        primary_metric="oracle_ratio",
        direction="maximize",
        mean=mean,
        std=0.0,
        ci95_low=mean,
        ci95_high=mean,
        case_count=10,
        observation_count=10,
        rank=rank,
        eligible_case_count=10,
        coverage_ratio=1.0,
        raw_rank=rank,
        qualified_rank=rank,
        constraint_status=status,
        constraint_qualified_rank=constraint_rank,
        constraint_reason=reason,
    )


def test_procurement_deep_dive_quantifies_auditability_gap_and_its_cause() -> None:
    rows = (
        _leaderboard("allocation-only", 1.0, rank=1, status="not_auditable", constraint_rank=None, reason="seller_ir_violation_count"),
        _leaderboard("mechanism", 0.8, rank=2, status="pass", constraint_rank=1),
        _leaderboard("violating", 0.7, rank=3, status="fail", constraint_rank=None, reason="budget_violation"),
    )

    (summary,) = procurement_auditability_rows(rows)

    assert summary.raw_winners == "allocation-only"
    assert summary.qualified_winners == "mechanism"
    assert summary.absolute_gap == pytest.approx(0.2)
    assert summary.relative_gap == pytest.approx(0.2)
    assert summary.pass_count == 1
    assert summary.fail_count == 1
    assert summary.not_auditable_count == 1
    assert summary.dominant_blocker == "seller_ir_violation_count"


def _result(
    family: str,
    case_id: str,
    setting: str,
    metrics: dict[str, float],
    **metadata,
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=f"{family}-{case_id}",
        track="trading" if setting.startswith("T-") else "valuation",
        method_id=family,
        case_id=case_id,
        seed=0,
        status="completed",
        metrics=metrics,
        runtime_seconds=0.01,
        metadata={
            "method_family": family,
            "benchmark_setting": setting,
            "implementation_kind": "native",
            "provenance_kind": "paper_variant",
            "pilot": False,
            **metadata,
        },
    )


def test_thickness_deep_dive_detects_capacity_limited_one_trade_rule() -> None:
    rows = tuple(
        _result(
            "one-trade",
            f"k{k}",
            "T-MARKET-THICKNESS",
            {"gain_from_trade_ratio": 1.0 / k, "trade_count": 1.0},
            efficient_trade_count=k,
            surplus_margin_profile="reference",
            primary_metric_eligible=True,
        )
        for k in (1, 3, 6, 12)
    )

    (summary,) = market_thickness_rows(rows, families={"one-trade"})

    assert summary.gft_k1 == pytest.approx(1.0)
    assert summary.gft_k12 == pytest.approx(1.0 / 12.0)
    assert summary.change_k1_to_k12 == pytest.approx(-11.0 / 12.0)
    assert summary.inverse_k_loss_r2 == pytest.approx(1.0)
    assert summary.trade_count_k12 == pytest.approx(1.0)
    assert summary.capacity_utilization_k12 == pytest.approx(1.0 / 12.0)


def test_replication_deep_dive_keeps_magnitude_and_rank_axes_separate() -> None:
    rows = (
        _result(
            "valuer",
            "c2",
            "V-REPLICATION-ROBUSTNESS",
            {
                "replication_owner_rank_change": 0.0,
                "replication_reward_share_gain": 0.1,
                "replication_score_inflation_ratio": 2.0,
            },
            replication_factor=2,
            primary_metric_eligible=True,
        ),
        _result(
            "valuer",
            "c4",
            "V-REPLICATION-ROBUSTNESS",
            {
                "replication_owner_rank_change": 0.0,
                "replication_reward_share_gain": 0.2,
                "replication_score_inflation_ratio": 6.0,
            },
            replication_factor=4,
            primary_metric_eligible=True,
        ),
    )

    (summary,) = replication_decomposition_rows(rows, families={"valuer"})

    assert summary.rank_change_factor2 == 0.0
    assert summary.rank_change_factor4 == 0.0
    assert summary.score_inflation_factor2 == pytest.approx(2.0)
    assert summary.score_inflation_factor4 == pytest.approx(6.0)
    assert summary.reward_share_gain_factor4 == pytest.approx(0.2)
    assert summary.worst_case_id == "c2"


def test_claim_deep_dive_recomputes_expected_claim_at_case_mean_level() -> None:
    spec = ExpectationSpec(
        expectation_id="expected-bound",
        family_id="randomized",
        setting="T-TEST",
        metric_id="welfare_ratio",
        claim_kind="theorem",
        relation="ge",
        target=0.25,
        tolerance=0.0,
        required_assumptions=("truthful_reports",),
        reference_key="paper",
        claim_location="Theorem 1",
    )
    values = {"c1": (0.2, 0.3), "c2": (0.0, 0.5)}
    rows = tuple(
        BenchmarkResult(
            run_id=f"{case}-{seed}",
            track="trading",
            method_id="randomized",
            case_id=case,
            seed=seed,
            status="completed",
            metrics={"welfare_ratio": value},
            runtime_seconds=0.01,
            metadata={
                "method_family": "randomized",
                "benchmark_setting": "T-TEST",
                "implementation_kind": "native",
                "case_assumptions": ("truthful_reports",),
            },
        )
        for case, case_values in values.items()
        for seed, value in enumerate(case_values)
    )

    (summary,) = claim_aggregation_rows(rows, specs=(spec,), minimum_cases=2)

    assert summary.observation_count == 4
    assert summary.run_not_met_count == 2
    assert summary.run_not_met_rate == pytest.approx(0.5)
    assert summary.case_count == 2
    assert summary.case_mean_not_met_count == 0
    assert summary.case_mean_not_met_rate == 0.0
    assert summary.verdict_shift is True
