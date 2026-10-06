import json
from pathlib import Path

import datamechbench.pg_elr_development as development_module
import pytest
from datamechbench.methods.valuation_multifidelity import BudgetDebitedConfig
from datamechbench.methods.valuation_slope_calibrated import SlopeCalibratedConfig
from datamechbench.pg_elr_development import (
    amortized_envelope_summary,
    append_result_rows,
    candidate_grid,
    iter_development_rows,
    load_real_development_games,
    make_run_id,
    real_build_spec,
    selection_rows,
)


def _write_game(
    root: Path, input_hash: str, content_hash: str, *, container: str = "games"
) -> None:
    game_dir = root / container / input_hash
    (game_dir / "coalitions").mkdir(parents=True)
    for mask in range(8):
        payload = {
            "mask": mask,
            "input_hash": input_hash,
            "fit_seconds": 0.1,
            "checkpoint_hashes": {},
            "utilities": {
                "low": mask / 20,
                "medium": mask / 10,
                "high": mask / 8,
            },
        }
        (game_dir / "coalitions" / f"{mask:04d}.json").write_text(
            json.dumps(payload)
        )
    (game_dir / ".complete.json").write_text(
        json.dumps(
            {
                "coalitions": 8,
                "content_hash": content_hash,
                "input_hash": input_hash,
                "table_hashes": {"low": "l", "medium": "m", "high": "h"},
            }
        )
    )


def _write_costs(root: Path) -> None:
    (root / "measured_costs_tabular.json").write_text(
        json.dumps(
            {
                "breast_cancer": {
                    "ratio_q1": 0.2,
                    "ratio_median": 0.25,
                    "ratio_q3": 0.3,
                },
                "wine": {
                    "ratio_q1": 0.3,
                    "ratio_median": 0.35,
                    "ratio_q3": 0.4,
                },
            }
        )
    )


def test_load_real_games_resolves_new_and_legacy_summaries(tmp_path: Path) -> None:
    _write_costs(tmp_path)
    _write_game(tmp_path, "new-input", "new-content")
    _write_game(tmp_path, "old-input", "old-content")
    (tmp_path / "breast_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-breast-rf-n3-iid-s11",
                "input_hash": "new-input",
                "partition": "iid",
            }
        )
    )
    (tmp_path / "wine_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-wine-rf-n3-quantity_skew-s47",
                "tables_hash": "old-content",
            }
        )
    )
    (tmp_path / "pg_elr_dual_probe_summary.json").write_text("{}")

    loaded = load_real_development_games(tmp_path)

    assert [item.dataset_id for item in loaded] == ["breast_cancer", "wine"]
    assert loaded[0].partition == "iid"
    assert loaded[1].partition == "quantity_skew"
    assert loaded[0].ratios == {"q1": 0.2, "median": 0.25, "q3": 0.3}
    assert loaded[0].game.low.fidelity == "medium"
    assert loaded[0].game.low.values[7] == pytest.approx(0.7)
    assert loaded[0].source_input_hash == "new-input"
    assert loaded[1].source_input_hash == "old-input"
    assert list(
        iter_development_rows(
            loaded,
            budgets=(192,),
            seeds=(0,),
            direct_methods=(),
            configs=(),
        )
    ) == []


def test_load_real_games_accepts_confirmatory_cache_layout(tmp_path: Path) -> None:
    _write_game(tmp_path, "fashion-input", "fashion-content", container="cache")
    (tmp_path / "measured_costs_confirmatory.json").write_text(
        json.dumps(
            {
                "fashion_mnist": {
                    "ratio_q1": 0.45,
                    "ratio_median": 0.5,
                    "ratio_q3": 0.55,
                }
            }
        )
    )
    (tmp_path / "fashion_mnist_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-fashion-head-n3-label_skew-s29",
                "input_hash": "fashion-input",
                "partition": "label_skew",
            }
        )
    )

    loaded = load_real_development_games(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].dataset_id == "fashion_mnist"
    assert loaded[0].game.modality == "image"


def test_candidate_grid_scales_calibration_budget_by_probe_size() -> None:
    grid = candidate_grid(owner_count=8, reference_budget=224)

    assert [(c.probe_players, len(c.calibration_seeds), c.calibration_budget) for c in grid] == [
        (4, 10, 14),
        (4, 20, 14),
        (4, 40, 14),
        (5, 10, 28),
        (5, 20, 28),
        (5, 40, 28),
        (6, 10, 56),
        (6, 20, 56),
        (6, 40, 56),
    ]


def test_run_ids_and_selection_rows_are_paired_and_resume_safe() -> None:
    config = BudgetDebitedConfig(4, tuple(range(10)), 14)
    first = make_run_id("game-hash", 192, 7, "bd_pg_elr", config)
    assert first == make_run_id("game-hash", 192, 7, "bd_pg_elr", config)
    assert first != make_run_id("game-hash", 192, 8, "bd_pg_elr", config)
    rows = [
        {
            "run_id": "base-a-0",
            "game_hash": "g",
            "dataset_id": "breast_cancer",
            "partition": "iid",
            "budget": 192,
            "seed": 0,
            "method_id": "baseline_a",
            "status": "completed",
            "score_mae": 0.4,
        },
        {
            "run_id": "base-a-1",
            "game_hash": "g",
            "dataset_id": "breast_cancer",
            "partition": "iid",
            "budget": 192,
            "seed": 1,
            "method_id": "baseline_a",
            "status": "completed",
            "score_mae": 0.2,
        },
        {
            "run_id": "base-b-0",
            "game_hash": "g",
            "dataset_id": "breast_cancer",
            "partition": "iid",
            "budget": 192,
            "seed": 0,
            "method_id": "baseline_b",
            "status": "completed",
            "score_mae": 0.25,
        },
        {
            "run_id": "base-b-1",
            "game_hash": "g",
            "dataset_id": "breast_cancer",
            "partition": "iid",
            "budget": 192,
            "seed": 1,
            "method_id": "baseline_b",
            "status": "completed",
            "score_mae": 0.15,
        },
        *[
            {
                "run_id": f"bd-{seed}",
                "game_hash": "g",
                "dataset_id": "breast_cancer",
                "partition": "iid",
                "budget": 192,
                "seed": seed,
                "method_id": "bd_pg_elr",
                "probe_players": 4,
                "calibration_seed_count": 10,
                "status": "completed",
                "score_mae": 0.1 + seed * 0.01,
                "owner_count": 8,
                "low_cost_ratio": 0.25,
                "diagnostics": {"probe_winners": ["x", "x"]},
            }
            for seed in (0, 1)
        ],
    ]

    selected, baseline_by_cell = selection_rows(
        rows,
        direct_methods=("baseline_a", "baseline_b"),
    )

    assert baseline_by_cell == {"g|192": "baseline_b"}
    assert [row["baseline_mae"] for row in selected] == [0.25, 0.15]
    assert all(row["routing_inputs"]["low_cost_ratio"] == 0.25 for row in selected)


def test_append_result_rows_deduplicates_existing_run_ids(tmp_path: Path) -> None:
    ledger = tmp_path / "raw.jsonl"
    assert append_result_rows(ledger, ({"run_id": "a", "value": 1},)) == 1
    assert append_result_rows(
        ledger,
        ({"run_id": "a", "value": 999}, {"run_id": "b", "value": 2}),
    ) == 1

    assert [json.loads(line) for line in ledger.read_text().splitlines()] == [
        {"run_id": "a", "value": 1},
        {"run_id": "b", "value": 2},
    ]


def test_real_build_specs_pin_public_features_and_model_families() -> None:
    breast = real_build_spec("breast_cancer")
    wine = real_build_spec("wine")
    adult = real_build_spec("adult")
    digits = real_build_spec("digits")
    ag_news = real_build_spec("ag_news")
    news = real_build_spec("20newsgroups")

    assert (adult.feature_kind, adult.model_family, adult.cap, adult.schema_id) == (
        "mixed_tabular_hashing",
        "boosting",
        6000,
        "adult-openml-1590-v1",
    )
    assert (ag_news.feature_kind, ag_news.model_family, ag_news.cap) == (
        "text_hashing",
        "neural_head",
        6000,
    )
    assert news == ag_news
    assert (digits.feature_kind, digits.model_family, digits.cap) == (
        "tabular_numeric",
        "neural_head",
        None,
    )
    assert breast == wine
    assert (breast.feature_kind, breast.model_family, breast.cap) == (
        "tabular_numeric",
        "tree_ensemble",
        None,
    )


def test_confirmatory_build_specs_pin_resnet_and_neural_head() -> None:
    fashion = real_build_spec("fashion_mnist")
    cifar = real_build_spec("cifar10_subset")

    assert fashion == cifar
    assert (fashion.feature_kind, fashion.model_family, fashion.cap) == (
        "resnet18_frozen",
        "neural_head",
        6000,
    )


def test_completed_rows_include_frozen_vector_and_market_metrics(tmp_path: Path) -> None:
    _write_costs(tmp_path)
    _write_game(tmp_path, "new-input", "new-content")
    (tmp_path / "breast_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-breast-rf-n3-iid-s11",
                "input_hash": "new-input",
                "partition": "iid",
                "owner_row_counts": {"owner-0": 5, "owner-1": 7, "owner-2": 9},
            }
        )
    )
    game = load_real_development_games(tmp_path)[0]

    row = next(
        iter_development_rows(
            (game,),
            budgets=(8,),
            seeds=(0,),
            direct_methods=("shapley_mc",),
            configs=(),
        )
    )

    assert row["status"] == "completed"
    assert set(row["score_metrics"]) == {
        "mae",
        "normalized_mae",
        "rmse",
        "max_owner_error",
        "spearman",
        "ndcg",
    }
    assert row["score_mae"] == row["score_metrics"]["mae"]
    assert set(row["market_metrics"]) == {
        "top_k",
        "knapsack",
        "sequential",
        "revenue_conservation_error",
        "rank_stability",
    }


def test_development_rows_forward_shared_scr_configuration_and_accounting(
    tmp_path: Path,
) -> None:
    _write_costs(tmp_path)
    _write_game(tmp_path, "new-input", "new-content")
    (tmp_path / "breast_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-breast-rf-n3-iid-s11",
                "input_hash": "new-input",
                "partition": "iid",
            }
        )
    )
    game = load_real_development_games(tmp_path)[0]

    rows = tuple(
        iter_development_rows(
            (game,),
            budgets=(8,),
            seeds=(5,),
            direct_methods=("scr_beta_zero", "scr_beta_one", "scr_shapley"),
            configs=(),
            scr_config=SlopeCalibratedConfig(ridge_relative=0.1),
            scr_accounting="cached",
        )
    )

    assert len(rows) == 3
    assert all(row["status"] == "completed" for row in rows)
    assert {row["diagnostics"]["beta_mode"] for row in rows} == {
        "zero",
        "one",
        "learned",
    }
    assert len(
        {tuple(row["diagnostics"]["sampled_high_masks"]) for row in rows}
    ) == 1
    assert all(row["scr_config"] == {"ridge_relative": 0.1, "folds": 2} for row in rows)
    assert all(row["scr_accounting"] == "cached" for row in rows)


def test_external_comparator_paths_are_forwarded_without_changing_estimand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_costs(tmp_path)
    _write_game(tmp_path, "new-input", "new-content")
    (tmp_path / "breast_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-breast-rf-n3-iid-s11",
                "input_hash": "new-input",
                "partition": "iid",
            }
        )
    )
    game = load_real_development_games(tmp_path)[0]
    original = development_module.evaluate_sota

    def fake_evaluate(method_id, table, *, budget, seed, **options):
        if method_id == "pydvl_vrds":
            assert options["pydvl_python"] == tmp_path / "pydvl-python"
            return original("exact_table", table, budget=len(table.values), seed=0)
        return original(method_id, table, budget=budget, seed=seed, **options)

    monkeypatch.setattr(development_module, "evaluate_sota", fake_evaluate)

    row = next(
        iter_development_rows(
            (game,),
            budgets=(8,),
            seeds=(0,),
            direct_methods=("pydvl_vrds",),
            configs=(),
            pydvl_python=tmp_path / "pydvl-python",
        )
    )

    assert row["status"] == "completed"
    assert row["score_mae"] == pytest.approx(0.0)


def test_fixed_medium_cost_above_budget_is_structured_not_applicable(
    tmp_path: Path,
) -> None:
    _write_costs(tmp_path)
    _write_game(tmp_path, "new-input", "new-content")
    (tmp_path / "breast_summary.json").write_text(
        json.dumps(
            {
                "setting_id": "real-breast-rf-n3-iid-s11",
                "input_hash": "new-input",
                "partition": "iid",
            }
        )
    )
    game = load_real_development_games(tmp_path)[0]

    row = next(
        iter_development_rows(
            (game,),
            budgets=(1,),
            seeds=(0,),
            direct_methods=("elr_residual_leverage",),
            configs=(),
        )
    )

    assert row["status"] == "skipped"
    assert row["error"].startswith("inapplicable_budget:")


def test_amortized_envelope_summary_is_cellwise_paired_and_conservative() -> None:
    rows = []
    for budget, pg_values, direct_a, direct_b in (
        (192, (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)),
        (224, (1.0, 2.0), (1.0, 2.0), (4.0, 4.0)),
    ):
        for seed in (0, 1):
            common = {
                "game_hash": "g",
                "dataset_id": "d",
                "partition": "iid",
                "budget": budget,
                "seed": seed,
                "status": "completed",
            }
            rows.extend(
                (
                    {
                        **common,
                        "method_id": "pg_elr_adaptive_direct",
                        "score_mae": pg_values[seed],
                    },
                    {**common, "method_id": "a", "score_mae": direct_a[seed]},
                    {**common, "method_id": "b", "score_mae": direct_b[seed]},
                )
            )

    summary = amortized_envelope_summary(rows, direct_methods=("a", "b"))

    assert summary["cell_count"] == 2
    assert summary["wins"] == 1
    assert summary["ties"] == 1
    assert summary["losses"] == 0
    assert summary["geometric_mean_mae_ratio"] == pytest.approx(2**-0.5)
    assert [cell["baseline_method"] for cell in summary["cells"]] == ["a", "a"]
    assert all("holm_adjusted_p_value" in cell for cell in summary["cells"])
