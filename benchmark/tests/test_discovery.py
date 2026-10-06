from __future__ import annotations

from dataclasses import replace

import pytest
from datamechbench.discovery import (
    assumption_transfer_discoveries,
    constraint_discoveries,
    expectation_discoveries,
    paired_discoveries,
    structural_discoveries,
)
from datamechbench.expectations import ExpectationSpec
from datamechbench.leaderboard import LeaderboardRow
from datamechbench.models import BenchmarkResult
from datamechbench.robustness import AssumptionTransferRow
from datamechbench.statistics import PairwiseComparison
from datamechbench.structural_profiles import StructuralProfile


def _profile(family: str, mean: float, slope: float) -> StructuralProfile:
    return StructuralProfile(
        track="procurement",
        setting="P-MARKET-CONCENTRATION",
        family_id=family,
        method_id=family,
        primary_metric="oracle_ratio",
        direction="maximize",
        axis_name="largest_singleton_share",
        block_name="budget_item_count",
        case_count=20,
        observation_count=20,
        block_count=4,
        expected_block_count=4,
        coverage_ratio=1.0,
        mean_primary=mean,
        worst_case_primary=mean - 0.2,
        oriented_axis_auc=mean,
        oriented_slope=slope,
        oriented_endpoint_change=slope,
        nondegradation_rate=1.0 if slope >= 0 else 0.0,
    )


def test_structural_discovery_separates_level_from_axis_response() -> None:
    findings = structural_discoveries(
        (
            _profile("high-level", 0.8, -0.2),
            _profile("responsive", 0.6, 0.4),
            _profile("common-baseline", 1.0, -1.0),
        ),
        eligible_families={"high-level", "responsive"},
    )

    tradeoff = next(row for row in findings if row.category == "level_response_tradeoff")
    assert tradeoff.family_a == "high-level"
    assert tradeoff.family_b == "responsive"
    assert tradeoff.effect_name == "oriented_level_advantage"
    assert tradeoff.effect_value == pytest.approx(0.2)
    assert tradeoff.secondary_effect_name == "oriented_slope_gap"
    assert tradeoff.secondary_effect_value == pytest.approx(-0.6)
    assert tradeoff.evidence_tier == "hypothesis_generating"
    assert tradeoff.case_count == 20
    assert tradeoff.coverage_ratio == 1.0


def test_structural_discovery_surfaces_mean_to_worst_case_fragility() -> None:
    stable = replace(_profile("stable", 0.7, 0.1), worst_case_primary=0.6)
    fragile = replace(_profile("fragile", 0.8, 0.1), worst_case_primary=0.0)

    findings = structural_discoveries((stable, fragile))

    gap = next(row for row in findings if row.category == "mean_worst_case_gap")
    assert gap.family_a == "fragile"
    assert gap.effect_name == "mean_to_worst_oriented_gap"
    assert gap.effect_value == pytest.approx(0.8)
    assert gap.secondary_effect_name == "worst_case_primary"
    assert gap.secondary_effect_value == 0.0
    assert gap.evidence_tier == "design_descriptive"


def _leaderboard_row(
    family: str,
    *,
    mean: float,
    rank: int,
    constraint_status: str,
    constraint_rank: int | None,
) -> LeaderboardRow:
    return LeaderboardRow(
        track="trading",
        setting="T-BILATERAL",
        scope="stable",
        family_id=family,
        method_id=family,
        primary_metric="gain_from_trade_ratio",
        direction="maximize",
        mean=mean,
        std=0.0,
        ci95_low=mean,
        ci95_high=mean,
        case_count=12,
        observation_count=12,
        rank=rank,
        eligible_case_count=12,
        coverage_ratio=1.0,
        raw_rank=rank,
        qualified_rank=rank,
        constraint_status=constraint_status,
        constraint_qualified_rank=constraint_rank,
    )


def test_constraint_discovery_reports_when_raw_winner_is_not_deployable() -> None:
    findings = constraint_discoveries(
        (
            _leaderboard_row("raw-winner", mean=1.0, rank=1, constraint_status="fail", constraint_rank=None),
            _leaderboard_row("qualified", mean=0.8, rank=2, constraint_status="pass", constraint_rank=1),
        )
    )

    (finding,) = findings
    assert finding.category == "constraint_displacement"
    assert finding.family_a == "raw-winner"
    assert finding.family_b == "qualified"
    assert finding.effect_name == "raw_to_constraint_qualified_rank"
    assert finding.effect_value == 1.0
    assert finding.evidence_tier == "constraint_audit"


def test_paired_discovery_only_promotes_multiplicity_corrected_differences() -> None:
    significant = PairwiseComparison(
        "trading", "T-MARKET-THICKNESS", "gain_from_trade_ratio", "maximize",
        "a", "b", 20, 0.2, 0.2, 0.1, 0.3, 15, 1, 4, 0.001, 0.01, "a_better",
    )
    inconclusive = PairwiseComparison(
        "trading", "T-MARKET-THICKNESS", "gain_from_trade_ratio", "maximize",
        "a", "c", 20, 0.3, 0.3, -0.1, 0.5, 12, 0, 8, 0.1, 0.2, "indistinguishable",
    )
    baseline = PairwiseComparison(
        "trading", "T-MARKET-THICKNESS", "gain_from_trade_ratio", "maximize",
        "common-baseline", "b", 20, 1.0, 1.0, 0.8, 1.2, 20, 0, 0, 0.001, 0.001, "a_better",
    )

    (finding,) = paired_discoveries(
        (significant, inconclusive, baseline), eligible_families={"a", "b", "c"}
    )

    assert finding.category == "paired_advantage"
    assert finding.family_a == "a"
    assert finding.family_b == "b"
    assert finding.effect_value == pytest.approx(0.2)
    assert finding.evidence_tier == "paired_supported"
    assert finding.case_count == 20


def test_expectation_discovery_reports_case_and_observation_denominators() -> None:
    spec = ExpectationSpec(
        expectation_id="paper-bound",
        family_id="paper-method",
        setting="T-DOUBLE",
        metric_id="max_deviation_gain",
        claim_kind="theorem",
        relation="le",
        target=0.0,
        tolerance=0.0,
        required_assumptions=("truthful_reports",),
        reference_key="paper",
        claim_location="Theorem 1",
    )
    results = tuple(
        BenchmarkResult(
            run_id=f"run-{index}",
            track="trading",
            method_id="paper-method",
            case_id=f"case-{index}",
            seed=0,
            status="completed",
            metrics={"max_deviation_gain": 0.2 if index < 2 else 0.0},
            runtime_seconds=0.01,
            metadata={
                "method_family": "paper-method",
                "benchmark_setting": "T-DOUBLE",
                "case_assumptions": ("truthful_reports",),
            },
        )
        for index in range(10)
    )

    (finding,) = expectation_discoveries(results, specs=(spec,))

    assert finding.category == "claim_boundary"
    assert finding.effect_name == "not_met_rate"
    assert finding.effect_value == pytest.approx(0.2)
    assert finding.secondary_effect_value == 2.0
    assert finding.case_count == 10
    assert finding.observation_count == 10
    assert finding.evidence_tier == "claim_diagnostic"


def _transfer(family: str, delta: float) -> AssumptionTransferRow:
    return AssumptionTransferRow(
        transfer_id="source-to-target",
        track="trading",
        family_id=family,
        source_setting="T-DOUBLE",
        target_setting="T-CORRELATED",
        primary_metric="gain_from_trade_ratio",
        direction="maximize",
        source_mean=0.7,
        target_mean=0.7 + delta,
        oriented_delta=delta,
        source_rank=2,
        target_rank=3,
        rank_change=1,
        source_coverage=1.0,
        target_coverage=1.0,
        source_constraint_status="pass",
        target_constraint_status="pass",
        status="matched",
        rationale="Tests transfer under correlation.",
    )


def test_transfer_discovery_keeps_largest_loss_and_gain() -> None:
    findings = assumption_transfer_discoveries((_transfer("fragile", -0.2), _transfer("resilient", 0.1)))

    assert {(row.family_a, row.effect_value) for row in findings} == {
        ("fragile", -0.2),
        ("resilient", 0.1),
    }
    assert {row.category for row in findings} == {"assumption_transfer"}
    assert all(row.evidence_tier == "design_descriptive" for row in findings)
