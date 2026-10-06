from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from datamechbench.elr_selection import (
    leave_one_dataset_out_select,
    write_selection_record,
)
from datamechbench.methods.valuation_multifidelity import BudgetDebitedConfig


def _config(k: int, m: int) -> BudgetDebitedConfig:
    return BudgetDebitedConfig(k, tuple(range(m)), 14 * (2 ** (k - 4)))


def _row(
    dataset: str,
    config: BudgetDebitedConfig,
    method_mae: float,
    baseline_mae: float = 1.0,
    *,
    status: str = "completed",
) -> dict[str, object]:
    return {
        "dataset_id": dataset,
        "partition": "iid",
        "budget": 192,
        "estimator_seed": 0,
        "probe_players": config.probe_players,
        "calibration_seed_count": len(config.calibration_seeds),
        "method_mae": method_mae,
        "baseline_mae": baseline_mae,
        "status": status,
        "routing_inputs": {
            "probe_median_mae": {"elr": 0.1, "svarm": 0.2},
            "probe_winners": ["elr", "elr"],
            "budget": 192,
            "low_cost_ratio": 0.1,
        },
    }


def test_lodo_selection_uses_lexicographic_objective_and_keeps_failures() -> None:
    k4_m10, k4_m20, k5_m10, k6_m10 = (
        _config(4, 10),
        _config(4, 20),
        _config(5, 10),
        _config(6, 10),
    )
    rows = []
    for dataset, errors in {
        "a": (0.95, 0.95, 0.80),
        "b": (0.95, 0.95, 1.10),
        "c": (1.10, 1.10, 1.10),
    }.items():
        rows.extend(
            (
                _row(dataset, k4_m10, errors[0]),
                _row(dataset, k4_m20, errors[1]),
                _row(dataset, k5_m10, errors[2]),
                _row(dataset, k6_m10, 9.0, status="failed"),
            )
        )

    summary = leave_one_dataset_out_select(
        rows,
        candidate_grid=(k4_m10, k4_m20, k5_m10, k6_m10),
    )

    assert summary.selected_config == k4_m10
    assert tuple(fold.held_out_dataset for fold in summary.folds) == ("a", "b", "c")
    assert all(fold.held_out_dataset not in fold.training_datasets for fold in summary.folds)
    assert len(summary.candidates) == 4
    failed = next(item for item in summary.candidates if item.config == k6_m10)
    assert failed.status == "failed"
    assert failed.failed_cells == 3


@pytest.mark.parametrize(
    "forbidden",
    [
        {"dataset_id": "secret"},
        {"model_family": "boosting"},
        {"test_metric": 0.1},
        {"confirmatory_result": "win"},
        {"selected_after_outcome": True},
    ],
)
def test_selection_rejects_forbidden_routing_inputs(forbidden: dict[str, object]) -> None:
    config = _config(4, 10)
    row = _row("a", config, 0.9)
    row["routing_inputs"] = {**row["routing_inputs"], **forbidden}

    with pytest.raises(ValueError, match="forbidden routing input"):
        leave_one_dataset_out_select((row,), candidate_grid=(config,))


def test_selection_rejects_top_level_confirmatory_or_model_fields() -> None:
    config = _config(4, 10)
    for key in ("model_family", "test_metric", "confirmatory_outcome"):
        row = _row("a", config, 0.9)
        row[key] = "leak"
        with pytest.raises(ValueError, match="forbidden selection field"):
            leave_one_dataset_out_select((row,), candidate_grid=(config,))


def test_selection_record_is_canonical_and_binds_source_hashes(tmp_path: Path) -> None:
    config = _config(4, 10)
    summary = leave_one_dataset_out_select(
        (_row("a", config, 0.9), _row("b", config, 0.8)),
        candidate_grid=(config,),
    )

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_hash = write_selection_record(
        summary, first, source_hashes={"method": "abc", "config": "def"}
    )
    second_hash = write_selection_record(
        summary, second, source_hashes={"config": "def", "method": "abc"}
    )

    assert first_hash == second_hash
    assert json.loads(first.read_text()) == json.loads(second.read_text())
    assert json.loads(first.read_text())["selection_hash"] == first_hash


def test_development_config_encodes_the_frozen_paper_protocol() -> None:
    config_path = Path(__file__).resolve().parents[1] / "configs/pg_elr_paper_development.yaml"
    config = yaml.safe_load(config_path.read_text())

    assert [item["id"] for item in config["datasets"]] == [
        "breast_cancer",
        "wine",
        "adult",
        "california_housing",
        "diabetes",
        "digits",
        "ag_news",
        "20_newsgroups",
    ]
    assert config["partitions"] == {
        "iid": {"seed": 11},
        "label_skew": {"seed": 29},
        "quantity_skew": {"seed": 47},
    }
    assert config["budgets"] == {"n8": [192, 224]}
    assert config["estimator_seeds"] == {"start": 0, "stop": 100}
    assert config["probe_grid"]["players"] == [4, 5, 6]
    assert config["probe_grid"]["seeds"] == [10, 20, 40]
    assert config["probe_grid"]["routing"] == "unanimous_else_shapiq_svarm"
    assert len(config["methods"]) >= 14
    assert "bd_pg_elr" in config["methods"]
    assert set(config["ratio_sensitivity"]) == {"q1", "median", "q3"}
    assert len(config["ablations"]) == 11
    assert config["physical_gpus"] == [1, 2, 3, 4, 5, 6, 7]
