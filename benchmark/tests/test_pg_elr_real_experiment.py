from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from datamechbench.real_experiment import append_pg_elr_rows, run_pg_elr_phase


def _config(path: Path, *, confirmatory_utilities=None) -> Path:
    payload = {
        "schema_version": "1.0",
        "study_id": "tiny-development",
        "phase": "development",
        "physical_gpus": [1, 2],
        "datasets": [{"id": "a", "owners": 8}],
        "partitions": {
            "iid": {"seed": 11},
            "label_skew": {"seed": 29},
            "quantity_skew": {"seed": 47},
        },
        "budgets": {"n8": [192]},
        "estimator_seeds": {"start": 0, "stop": 3},
        "methods": ["shapiq_svarm", "bd_pg_elr"],
        "probe_grid": {"players": [4, 5], "seeds": [10]},
        "confirmatory_utilities": confirmatory_utilities,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True))
    return path


def test_pg_elr_dry_run_expands_deterministic_tasks_without_results(tmp_path: Path) -> None:
    config = _config(tmp_path / "development.yaml")
    first = run_pg_elr_phase(
        config,
        phase="development",
        output_dir=tmp_path / "out-a",
        resume=False,
        gpu_ids=(1, 2),
        dry_run=True,
    )
    second = run_pg_elr_phase(
        config,
        phase="development",
        output_dir=tmp_path / "out-b",
        resume=False,
        gpu_ids=(1, 2),
        dry_run=True,
    )

    assert first["task_count"] == 27
    assert first["run_ids"] == second["run_ids"]
    assert len(set(first["run_ids"])) == 27
    assert first["completed_run_ids"] == []
    assert not (tmp_path / "out-a" / "raw_results.jsonl").exists()
    assert json.loads((tmp_path / "out-a" / "task_manifest.json").read_text())[
        "task_count"
    ] == 27


def _result(run_id: str, config_hash: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "config_hash": config_hash,
        "status": "completed",
        "preprocessing_seconds": 0.1,
        "calibration_seconds": 0.2,
        "production_seconds": 0.3,
        "logical_calls": 10,
        "physical_calls": 9,
        "unique_masks": 8,
        "cost_ratio_median": 0.1,
        "cost_ratio_q1": 0.08,
        "cost_ratio_q3": 0.12,
        "source_hash": "source",
        "feature_hash": "feature",
        "model_hash": "model",
    }


def test_append_only_rows_deduplicate_and_resume(tmp_path: Path) -> None:
    config = _config(tmp_path / "development.yaml")
    initial = run_pg_elr_phase(
        config,
        phase="development",
        output_dir=tmp_path / "out",
        resume=False,
        gpu_ids=(1,),
        dry_run=True,
    )
    row = _result(initial["run_ids"][0], initial["config_hash"])
    raw = tmp_path / "out" / "raw_results.jsonl"

    assert append_pg_elr_rows(raw, (row,), expected_config_hash=initial["config_hash"]) == 1
    assert append_pg_elr_rows(raw, (row,), expected_config_hash=initial["config_hash"]) == 0
    resumed = run_pg_elr_phase(
        config,
        phase="development",
        output_dir=tmp_path / "out",
        resume=True,
        gpu_ids=(1,),
        dry_run=True,
    )

    assert resumed["completed_run_ids"] == [row["run_id"]]
    assert resumed["remaining_task_count"] == 26
    assert len(raw.read_text().splitlines()) == 1


def test_resume_rejects_corrupt_or_incompatible_rows(tmp_path: Path) -> None:
    config = _config(tmp_path / "development.yaml")
    output = tmp_path / "out"
    output.mkdir()
    raw = output / "raw_results.jsonl"
    raw.write_text("not-json\n")
    with pytest.raises(ValueError, match="corrupt append-only row"):
        run_pg_elr_phase(
            config,
            phase="development",
            output_dir=output,
            resume=True,
            gpu_ids=(1,),
            dry_run=True,
        )

    raw.write_text(json.dumps(_result("x", "wrong-config")) + "\n")
    with pytest.raises(ValueError, match="config hash"):
        run_pg_elr_phase(
            config,
            phase="development",
            output_dir=output,
            resume=True,
            gpu_ids=(1,),
            dry_run=True,
        )


@pytest.mark.parametrize("gpu_ids", [(0,), (8,), (1, 1), ()])
def test_pg_elr_runner_rejects_invalid_physical_gpu_ids(
    tmp_path: Path, gpu_ids: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError, match="GPU"):
        run_pg_elr_phase(
            _config(tmp_path / "development.yaml"),
            phase="development",
            output_dir=tmp_path / "out",
            resume=False,
            gpu_ids=gpu_ids,
            dry_run=True,
        )


def test_development_runner_rejects_confirmatory_utilities(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirmatory utilities"):
        run_pg_elr_phase(
            _config(tmp_path / "development.yaml", confirmatory_utilities={"secret": 1}),
            phase="development",
            output_dir=tmp_path / "out",
            resume=False,
            gpu_ids=(1,),
            dry_run=True,
        )
