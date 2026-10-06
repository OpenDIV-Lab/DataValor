from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from datamechbench.aggregate_type_envelope import (
    ENVELOPE_METHOD_IDS,
    build_aggregate_type_artifacts,
    build_aggregate_type_cases,
    find_rank_reversals,
    run_aggregate_type_envelope,
    summarize_admissibility_relaxations,
    summarize_aggregate_type_cells,
    summarize_aggregate_type_methods,
    summarize_headline_regret,
    summarize_joint_admissibility,
    summarize_point_selection_transfer,
    summarize_selection_views,
    verify_aggregate_type_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "benchmark" / "catalog" / "aggregate_type_envelope.yaml"
FINITE_AUDIT = (
    ROOT / "benchmark" / "outputs" / "kdd_finite_incentives" / "audit_results.json"
)


def _catalog() -> dict[str, object]:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def test_aggregate_type_cases_preserve_published_anchor_counts_without_microdata() -> None:
    cases = build_aggregate_type_cases(_catalog())

    assert len(cases) == 9
    assert {case.metadata["seller_position"] for case in cases} == {
        "lower",
        "midpoint",
        "upper",
    }
    assert {case.metadata["buyer_position"] for case in cases} == {
        "lower",
        "midpoint",
        "upper",
    }
    for case in cases:
        assert len(case.public.seller_ids) == 69
        assert len(case.public.buyer_ids) == 100
        assert case.metadata["source_sample_size"] == 2082
        assert case.metadata["unresolved_seller_share"] == 0.31
        assert case.metadata["not_microdata"] is True
        assert case.metadata["evidence_scope"] == (
            "aggregate_anchor_compatible_model_stress"
        )
        asks = [case.public.asks[seller] for seller in case.public.seller_ids]
        bids = [case.public.bids[buyer] for buyer in case.public.buyer_ids]
        assert asks == sorted(asks)
        assert bids == sorted(bids, reverse=True)
        assert len(set(asks)) == 69
        assert len(set(bids)) == 91
        assert sum(ask <= Decimal("1") for ask in asks) == 4
        assert sum(ask <= Decimal("4.3") for ask in asks) == 20
        assert sum(ask <= Decimal("10.75") for ask in asks) == 38
        assert sum(ask <= Decimal("37.84") for ask in asks) == 51
        assert sum(ask <= Decimal("73.1") for ask in asks) == 64
        assert sum(ask <= Decimal("148.78") for ask in asks) == 69
        assert sum(bid >= Decimal("1") for bid in bids) == 99
        assert sum(bid >= Decimal("4.3") for bid in bids) == 90
        assert sum(bid >= Decimal("10.75") for bid in bids) == 75
        assert sum(bid >= Decimal("37.84") for bid in bids) == 50
        assert sum(bid >= Decimal("73.1") for bid in bids) == 25
        assert sum(bid >= Decimal("148.78") for bid in bids) == 10


def test_aggregate_type_study_runs_eleven_categorized_mechanisms_on_nine_profiles() -> None:
    rows = run_aggregate_type_envelope(_catalog(), seeds=(0, 1))

    assert len(ENVELOPE_METHOD_IDS) == 11
    assert set(row.method_id for row in rows) == set(ENVELOPE_METHOD_IDS)
    assert len(rows) == 135
    assert len({row.case_id for row in rows}) == 9
    assert {row.comparison_group for row in rows} == {
        "headline_reference",
        "canonical_guardrail",
        "pricing_baseline",
        "diagnostic_reference",
    }
    assert all(0 <= row.gain_from_trade_ratio <= 1 for row in rows)
    assert all(row.individual_rationality for row in rows)
    assert any(not row.weak_budget_balance for row in rows)
    assert all(row.evidence_scope == "aggregate_anchor_compatible_model_stress" for row in rows)


def test_aggregate_type_summary_reports_robustness_ranges_and_rank_reversals() -> None:
    rows = run_aggregate_type_envelope(_catalog())
    cells = summarize_aggregate_type_cells(rows)
    methods = summarize_aggregate_type_methods(cells)
    reversals = find_rank_reversals(cells)
    regret = summarize_headline_regret(cells)

    assert len(cells) == 99
    assert len(methods) == 11
    assert all(row.profile_count == 9 for row in methods)
    assert all(row.comparison_group for row in methods)
    assert all(
        row.worst_profile_gft <= row.macro_expected_gft <= row.best_profile_gft
        for row in methods
    )
    vcg = next(row for row in methods if row.method_id == "vcg_double_auction")
    assert vcg.comparison_group == "canonical_guardrail"
    assert vcg.minimum_weak_budget_balance_rate == 0.0
    assert vcg.weak_budget_balance_profile_pass_count == 0
    midpoint = next(row for row in methods if row.method_id == "midpoint_double")
    assert midpoint.minimum_strong_budget_balance_rate == 1.0
    assert midpoint.strong_budget_balance_profile_pass_count == 9
    assert any(
        {row.method_a, row.method_b} == {"mcafee", "sbba"}
        and row.minimum_difference < 0 < row.maximum_difference
        for row in reversals
    )
    assert {row.method_id for row in regret if row.minimax_selected} == {
        "mcafee",
        "trade_reduction",
    }
    mcafee_regret = next(row for row in regret if row.method_id == "mcafee")
    trade_regret = next(row for row in regret if row.method_id == "trade_reduction")
    assert mcafee_regret.worst_profile_regret == pytest.approx(
        0.0009728103638072527
    )
    assert trade_regret.worst_profile_regret == pytest.approx(
        mcafee_regret.worst_profile_regret
    )
    assert mcafee_regret.macro_profile_regret < trade_regret.macro_profile_regret


def test_point_profile_selection_exposes_transfer_regret_and_tie_break_risk() -> None:
    rows = run_aggregate_type_envelope(_catalog())
    cells = summarize_aggregate_type_cells(rows)
    transfer = summarize_point_selection_transfer(cells)

    assert len(transfer) == 9
    sbba_only = next(
        row
        for row in transfer
        if row.selection_profile_id == "TAGG-smidpoint-blower"
    )
    assert sbba_only.selected_method_ids == "sbba"
    assert sbba_only.worst_optimistic_transfer_regret == pytest.approx(
        0.0059666472310525576
    )
    assert sbba_only.worst_optimistic_target_profile_id == (
        "TAGG-smidpoint-bmidpoint"
    )
    tied = next(
        row
        for row in transfer
        if row.selection_profile_id == "TAGG-supper-bmidpoint"
    )
    assert tied.selected_method_ids == "mcafee;sbba"
    assert tied.worst_optimistic_transfer_regret < (
        tied.worst_pessimistic_transfer_regret
    )
    assert tied.worst_pessimistic_transfer_regret == pytest.approx(
        sbba_only.worst_optimistic_transfer_regret
    )


def test_constraint_fidelity_views_report_winner_multiplicity_and_selection_cost() -> None:
    catalog = _catalog()
    rows = run_aggregate_type_envelope(catalog)
    cells = summarize_aggregate_type_cells(rows)
    profiles, summaries = summarize_selection_views(cells, catalog)

    assert len(profiles) == 45
    assert len(summaries) == 5
    by_id = {row.view_id: row for row in summaries}
    assert by_id["unrestricted_all"].eligible_method_count == 11
    assert by_id["observed_ir_wbb"].eligible_method_count == 10
    assert by_id["headline_ir_wbb"].eligible_method_count == 5
    assert by_id["paper_exact_ir_wbb"].eligible_method_count == 3
    strict = by_id["paper_exact_ir_wbb_sbb"]
    assert strict.eligible_method_count == 1
    assert strict.winner_union_ids == "mcafee;sbba"
    assert strict.winner_intersection_ids == "sbba"
    assert strict.max_shortfall_vs_unrestricted == pytest.approx(
        0.0066732787618392075
    )
    assert strict.worst_profile_id == "TAGG-slower-bmidpoint"


def test_joint_admissibility_gate_keeps_constraint_and_finite_evidence_conjunctive() -> None:
    rows = run_aggregate_type_envelope(_catalog())
    cells = summarize_aggregate_type_cells(rows)
    finite = json.loads(FINITE_AUDIT.read_text(encoding="utf-8"))
    joint = summarize_joint_admissibility(cells, finite)

    assert len(joint) == 5
    assert not any(row.joint_admissible for row in joint)
    mcafee = next(row for row in joint if row.method_id == "mcafee")
    assert mcafee.finite_no_counterexample_on_declared_estimand is True
    assert mcafee.exclusion_reasons == "strong_budget_balance"
    trade = next(row for row in joint if row.method_id == "trade_reduction")
    assert trade.exclusion_reasons == "strong_budget_balance"
    sbba = next(row for row in joint if row.method_id == "sbba")
    assert sbba.strong_budget_balance_all_profiles is True
    assert sbba.finite_no_counterexample_on_declared_estimand is False
    assert sbba.exclusion_reasons == "finite_counterexample"


def test_admissibility_relaxation_frontier_identifies_active_tradeoffs() -> None:
    rows = run_aggregate_type_envelope(_catalog())
    cells = summarize_aggregate_type_cells(rows)
    finite = json.loads(FINITE_AUDIT.read_text(encoding="utf-8"))
    joint = summarize_joint_admissibility(cells, finite)
    frontier = summarize_admissibility_relaxations(cells, joint)

    assert len(frontier) == 6
    by_id = {row.relaxation_id: row for row in frontier}
    assert by_id["full_gate"].admitted_method_count == 0
    assert by_id["drop_source_fidelity"].admitted_method_count == 0
    assert by_id["drop_individual_rationality"].admitted_method_count == 0
    assert by_id["drop_weak_budget_balance"].admitted_method_count == 0

    drop_sbb = by_id["drop_strong_budget_balance"]
    assert drop_sbb.admitted_method_ids == "mcafee;trade_reduction"
    assert drop_sbb.max_shortfall_vs_headline_best == pytest.approx(
        0.0009728103638072527
    )
    assert drop_sbb.max_shortfall_vs_unrestricted == pytest.approx(
        0.003211222043281725
    )

    drop_finite = by_id["drop_finite_no_counterexample"]
    assert drop_finite.admitted_method_ids == "sbba"
    assert drop_finite.max_shortfall_vs_headline_best == pytest.approx(
        0.0059666472310525576
    )
    assert drop_finite.max_shortfall_vs_headline_best / (
        drop_sbb.max_shortfall_vs_headline_best
    ) == pytest.approx(6.133412485143668)


def test_aggregate_type_artifact_build_is_self_verifying(tmp_path: Path) -> None:
    output = tmp_path / "aggregate-envelope"
    built = build_aggregate_type_artifacts(output, CATALOG, seeds=(0, 1))
    verified = verify_aggregate_type_artifacts(output / "manifest.json")

    assert built["valid"] is True
    assert built["run_count"] == 135
    assert built["profile_count"] == 9
    assert built["method_count"] == 11
    assert built["headline_method_count"] == 5
    assert built["all_method_rank_reversal_count"] >= built["rank_reversal_count"]
    assert (output / "all_method_rank_reversals.csv").is_file()
    assert (output / "headline_regret_summary.csv").is_file()
    assert (output / "point_selection_transfer.csv").is_file()
    assert (output / "selection_view_profile.csv").is_file()
    assert (output / "selection_view_summary.csv").is_file()
    assert (output / "joint_admissibility.csv").is_file()
    assert (output / "admissibility_relaxation_frontier.csv").is_file()
    findings = json.loads((output / "findings.json").read_text(encoding="utf-8"))
    assert all(
        "vcg_double_auction" in row["winner_ids"]
        for row in findings["raw_gft_profile_winners"]
    )
    assert all(
        "vcg_double_auction" not in row["winner_ids"]
        for row in findings["ir_wbb_qualified_gft_profile_winners"]
    )
    assert findings["qualification_boundary"] == (
        "IR and WBB only; source fidelity and strategic guarantees remain separate"
    )
    assert findings["headline_minimax_regret_method_ids"] == [
        "mcafee",
        "trade_reduction",
    ]
    assert findings["point_selection_worst_regret_inflation"] > 5.0
    assert findings["optimistically_fragile_selection_profile_count"] == 2
    assert findings["pessimistically_fragile_selection_profile_count"] == 3
    assert findings["strict_selection_view_id"] == "paper_exact_ir_wbb_sbb"
    assert findings["strict_selection_winner_union_ids"] == ["mcafee", "sbba"]
    assert findings["strict_selection_winner_intersection_ids"] == ["sbba"]
    assert findings["strict_selection_max_shortfall_vs_unrestricted"] > 0.006
    assert findings["joint_admissible_method_count"] == 0
    assert findings["joint_near_miss_method_ids"] == [
        "mcafee",
        "sbba",
        "trade_reduction",
    ]
    assert findings["admissibility_active_relaxations"] == [
        "finite_no_counterexample",
        "strong_budget_balance",
    ]
    assert findings["admissibility_relaxation_regret_inflation"] > 1.0
    assert verified == built
