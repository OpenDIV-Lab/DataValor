from __future__ import annotations

import json
import shutil
from pathlib import Path

from datamechbench.external_validation import audit_external_implementation_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_opendataval_crosscheck_executes_three_fixtures_and_builds_valid_record(
    tmp_path: Path,
) -> None:
    from datamechbench.external_knn_validation import (
        build_opendataval_knn_validation,
    )

    repository = tmp_path / "repo"
    external = repository / "benchmark/external/opendataval"
    scripts = repository / "benchmark/scripts"
    evidence = repository / "benchmark/evidence"
    external.mkdir(parents=True)
    scripts.mkdir(parents=True)
    evidence.mkdir(parents=True)
    for name in ("knnshap.py", "LICENSE.txt", "knn_shapley_fixtures.json"):
        shutil.copy2(
            REPOSITORY_ROOT / "benchmark/external/opendataval" / name,
            external / name,
        )
    shutil.copy2(
        REPOSITORY_ROOT / "benchmark/scripts/run_external_knn_validation.py",
        scripts / "run_external_knn_validation.py",
    )
    result = build_opendataval_knn_validation(
        source_path=external / "knnshap.py",
        license_path=external / "LICENSE.txt",
        fixture_path=external / "knn_shapley_fixtures.json",
        runner_path=scripts / "run_external_knn_validation.py",
        output_directory=evidence,
        repository_root=repository,
    )

    assert result["fixture_count"] == 3
    assert result["all_close"] is True
    assert result["maximum_absolute_error"] <= 1e-7
    assert set(result["execution_environment"]) == {
        "numpy",
        "python",
        "scikit_learn",
        "torch",
        "tqdm",
    }
    assert result["execution_environment"]["torch"].startswith("2.9.0")
    assert result["source_execution"] == (
        "unchanged_upstream_file_with_minimal_api_import_shim"
    )
    assert [item["case_id"] for item in result["comparisons"]] == [
        "binary-alternating-k2",
        "binary-two-validation-k3",
        "multiclass-two-dimensional-k2",
    ]
    assert all(item["owner_ids"] == [f"o{i}" for i in range(len(item["local_scores"]))]
               for item in result["comparisons"])
    record = evidence / "external_opendataval_knn_shapley_v1.json"
    assert record.is_file()
    audit = audit_external_implementation_records(
        (record.relative_to(repository).as_posix(),),
        repository,
        expected_method_ids={"knn_shapley"},
        minimum_records=1,
        minimum_fixtures=3,
    )
    assert audit["passed"] is True

    stored = json.loads(
        (evidence / "external_opendataval_knn_shapley_results_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == result
