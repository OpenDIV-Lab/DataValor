from __future__ import annotations

from datamechbench.coalition_games import CoalitionGameTable
from datamechbench.elr_study import (
    DEFAULT_METHODS,
    PAPER_COMPARATORS,
    StudyGame,
    resolve_amortized_disagreement,
    resolve_probe_winners,
    run_cached_table_study,
    select_probe_gated_sampler,
)
from datamechbench.methods.valuation_slope_calibrated import SlopeCalibratedConfig


def test_probe_disagreement_conservatively_falls_back_to_svarm() -> None:
    assert resolve_probe_winners(("elr_residual_leverage",) * 2) == "elr_residual_leverage"
    assert resolve_probe_winners(
        ("elr_residual_leverage", "shapiq_svarm")
    ) == "shapiq_svarm"


def test_amortized_disagreement_uses_lower_risk_direct_fallback() -> None:
    assert resolve_amortized_disagreement(
        ("shapiq_leverage_shap", "elr_residual_leverage"),
        {
            "elr_residual_leverage": 0.000035,
            "shapiq_leverage_shap": 0.000031,
            "shapiq_svarm": 0.000055,
        },
    ) == "shapiq_leverage_shap"
    assert resolve_amortized_disagreement(
        ("elr_residual_leverage", "shapiq_svarm"),
        {
            "elr_residual_leverage": 0.02,
            "shapiq_leverage_shap": 0.20,
            "shapiq_svarm": 0.03,
        },
    ) == "shapiq_svarm"


def test_cached_table_study_compares_same_target_methods_at_matched_budget() -> None:
    owners = ("o0", "o1", "o2")
    high = CoalitionGameTable(
        owners,
        {mask: float(mask.bit_count()) + 0.1 * float(mask == 7) for mask in range(8)},
        "high",
    )
    low = CoalitionGameTable(
        owners,
        {mask: 0.9 * float(mask.bit_count()) for mask in range(8)},
        "low",
    )
    game = StudyGame(
        "fixture", "tabular", "tree_ensemble", "ensemble_width", high, low
    )
    rows = run_cached_table_study(
        (game,),
        budgets=(24,),
        seeds=(0, 1),
        method_ids=(
            "shapley_exact_low_residual",
            "elr_residual_leverage",
            "shapiq_svarm",
        ),
        low_cost_ratio=0.1,
    )
    assert len(rows) == 6
    assert {row.method_id for row in rows} == {
        "shapley_exact_low_residual",
        "elr_residual_leverage",
        "shapiq_svarm",
    }
    assert all(row.status == "completed" for row in rows)
    assert all(row.metadata["estimand"] == "ordinary_shapley" for row in rows)
    assert all(row.metadata["equivalent_budget"] == 24 for row in rows)
    assert all(row.metrics["score_mae"].applicable for row in rows)


def test_scr_modes_share_high_samples_budget_and_ordinary_shapley_target() -> None:
    owners = tuple(f"o{index}" for index in range(6))
    low_values = {mask: float(mask.bit_count() ** 2) for mask in range(64)}
    high_values = {
        mask: 1.7 * value + 0.03 * float((mask * 11) % 7)
        for mask, value in low_values.items()
    }
    game = StudyGame(
        "scr-fixture",
        "tabular",
        "tree_ensemble",
        "ensemble_width",
        CoalitionGameTable(owners, high_values, "high"),
        CoalitionGameTable(owners, low_values, "medium"),
    )

    rows = run_cached_table_study(
        (game,),
        budgets=(48,),
        seeds=(17,),
        method_ids=("scr_beta_zero", "scr_beta_one", "scr_shapley"),
        low_cost_ratio=0.25,
        scr_config=SlopeCalibratedConfig(ridge_relative=0.1),
        scr_accounting="cached",
    )

    assert all(row.status == "completed" for row in rows)
    assert all(row.metadata["estimand"] == "ordinary_shapley" for row in rows)
    diagnostics = [row.metadata["diagnostics"] for row in rows]
    assert len({tuple(item["sampled_high_masks"]) for item in diagnostics}) == 1
    assert len({item["paired_high_calls"] for item in diagnostics}) == 1
    assert {item["beta_mode"] for item in diagnostics} == {"zero", "one", "learned"}
    assert all(item["accounting"] == "cached" for item in diagnostics)
    assert all(item["low_equivalent_cost"] == 0.0 for item in diagnostics)


def test_scr_strict_accounting_reports_low_table_cost_as_structured_skip() -> None:
    owners = tuple(f"o{index}" for index in range(4))
    values = {mask: float(mask.bit_count()) for mask in range(16)}
    game = StudyGame(
        "scr-strict",
        "tabular",
        "tree_ensemble",
        "ensemble_width",
        CoalitionGameTable(owners, values, "high"),
        CoalitionGameTable(owners, values, "medium"),
    )

    [row] = run_cached_table_study(
        (game,),
        budgets=(8,),
        seeds=(0,),
        method_ids=("scr_shapley",),
        low_cost_ratio=0.5,
        scr_config=SlopeCalibratedConfig(ridge_relative=0.1),
        scr_accounting="strict",
    )

    assert row.status == "skipped"
    assert row.error == "inapplicable_budget:low_table_consumes_budget"
    diagnostics = row.metadata["diagnostics"]
    assert diagnostics["declared_budget"] == 8
    assert diagnostics["low_equivalent_cost"] == 8.0
    assert diagnostics["required_calls"] == 2
    assert diagnostics["available_calls"] == 0


def test_real_study_routes_native_baselines_and_marks_real_evidence() -> None:
    owners = ("o0", "o1", "o2")
    high = CoalitionGameTable(
        owners, {mask: float(mask.bit_count() ** 2) for mask in range(8)}, "high"
    )
    low = CoalitionGameTable(
        owners, {mask: 0.8 * float(mask.bit_count() ** 2) for mask in range(8)}, "low"
    )
    rows = run_cached_table_study(
        (
            StudyGame(
                "real-fixture",
                "tabular",
                "tree_ensemble",
                "ensemble_width",
                high,
                low,
                evidence_scope="real_trained_game",
            ),
        ),
        budgets=(24,),
        seeds=(0,),
        method_ids=("shapley_mc", "tmc_shapley", "owen_shapley", "shapley_antithetic"),
        low_cost_ratio=0.1,
    )
    assert all(row.status == "completed" for row in rows)
    assert all(row.metadata["evidence_scope"] == "real_trained_game" for row in rows)


def test_probe_gated_elr_selects_on_six_owner_subgame_and_records_calibration() -> None:
    owners = tuple(f"o{index}" for index in range(8))
    values = {
        mask: float(mask.bit_count() ** 2 + 0.17 * ((mask * 13) % 11))
        for mask in range(256)
    }
    high = CoalitionGameTable(owners, values, "high")
    low = CoalitionGameTable(owners, values, "medium")
    game = StudyGame(
        "probe-fixture",
        "tabular",
        "boosting",
        "boosting_round_prefix",
        high,
        low,
        evidence_scope="real_trained_game",
    )

    selection = select_probe_gated_sampler(
        game, low_cost_ratio=0.1, calibration_seeds=range(4)
    )
    repeated = select_probe_gated_sampler(
        game, low_cost_ratio=0.1, calibration_seeds=range(4)
    )
    assert repeated is selection
    assert selection.selected_method == "elr_residual_leverage"
    assert selection.probe_players == 6
    assert selection.probe_winners == (
        "elr_residual_leverage",
        "elr_residual_leverage",
    )
    assert selection.calibration_high_calls == 112

    [row] = run_cached_table_study(
        (game,),
        budgets=(80,),
        seeds=(7,),
        method_ids=("pg_elr",),
        low_cost_ratio=0.1,
    )
    assert row.status == "completed"
    diagnostics = row.metadata["diagnostics"]
    assert diagnostics["selected_method"] == "elr_residual_leverage"
    assert diagnostics["calibration_high_calls"] == 112
    assert diagnostics["calibration_cost_accounting"] == "one_time_amortized"


def test_budget_debited_pg_elr_is_registered_and_structures_inapplicability() -> None:
    owners = tuple(f"o{index}" for index in range(8))
    values = {mask: float(mask.bit_count()) for mask in range(256)}
    game = StudyGame(
        "strict-inapplicable",
        "tabular",
        "boosting",
        "stage_prefix",
        CoalitionGameTable(owners, values, "high"),
        CoalitionGameTable(owners, values, "medium"),
    )

    [row] = run_cached_table_study(
        (game,),
        budgets=(100,),
        seeds=(0,),
        method_ids=("bd_pg_elr",),
        low_cost_ratio=0.1,
    )

    assert "bd_pg_elr" in DEFAULT_METHODS
    assert row.status == "skipped"
    assert row.error.startswith("inapplicable_budget:")
    assert row.metadata["diagnostics"]["reason"] == "probe_cost_exceeds_budget"
    assert row.metadata["diagnostics"]["probe_high_calls"] == 112


def test_paper_comparator_matrix_has_same_estimand_and_required_methods() -> None:
    required_direct = {
        "shapiq_svarm",
        "shapiq_stratified_sampling",
        "shapiq_kernel_shap",
        "shapiq_unbiased_kernel_shap",
        "shapiq_owen",
        "shapiq_leverage_shap",
        "shapley_mc",
        "tmc_shapley",
        "owen_shapley",
        "shapley_antithetic",
        "shapley_stratified",
    }
    specs = {spec.method_id: spec for spec in PAPER_COMPARATORS}

    assert required_direct <= set(specs)
    assert {"elr_residual_leverage", "pg_elr", "bd_pg_elr"} <= set(specs)
    assert all(spec.estimand == "ordinary_group_data_shapley" for spec in specs.values())
    assert all(specs[method].category == "direct_high_fidelity" for method in required_direct)
    assert required_direct <= set(DEFAULT_METHODS)
    assert {"pydvl_vrds", "pydvl_owen", "pydvl_group_testing"} <= set(DEFAULT_METHODS)


def test_optional_comparators_are_declared_external_not_local_lookalikes() -> None:
    specs = {spec.method_id: spec for spec in PAPER_COMPARATORS}
    optional = {
        "official_stratified_svarm",
        "official_stratified_svarm_plus",
        "pydvl_vrds",
        "pydvl_owen",
        "pydvl_group_testing",
    }

    assert optional <= set(specs)
    assert all(specs[name].implementation_kind == "official_external" for name in optional)
    assert all(specs[name].unavailable_policy == "structured_na" for name in optional)
    assert all(specs[name].source not in {"DataValor", "local_reimplementation"} for name in optional)
