from __future__ import annotations

import json
import shutil
from pathlib import Path

from datamechbench.external_validation import audit_external_implementation_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_svarm_exact_shapley_crosscheck_executes_shared_and_boundary_fixtures(
    tmp_path: Path,
) -> None:
    from datamechbench.external_shapley_validation import (
        build_svarm_exact_shapley_validation,
    )

    repository = tmp_path / "repo"
    source_root = REPOSITORY_ROOT / "benchmark/external/svarm_exact_snapshot"
    external = repository / "benchmark/external/svarm_official"
    scripts = repository / "benchmark/scripts"
    evidence = repository / "benchmark/evidence"
    external.mkdir(parents=True)
    scripts.mkdir(parents=True)
    evidence.mkdir(parents=True)
    source_files = (
        "ApproxMethods/GroundTruth/ExhaustiveSearch.py",
        "ApproxMethods/AbstractApproxMethod.py",
        "Experiment/ExperimentData.py",
        "utils/utils.py",
        "LICENSE",
        "exact_shapley_fixtures.json",
    )
    for name in source_files:
        destination = external / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / name, destination)
    runner = scripts / "run_external_shapley_validation.py"
    shutil.copy2(
        REPOSITORY_ROOT / "benchmark/scripts/run_external_shapley_validation.py",
        runner,
    )

    result = build_svarm_exact_shapley_validation(
        external_directory=external,
        fixture_path=external / "exact_shapley_fixtures.json",
        runner_path=runner,
        output_directory=evidence,
        repository_root=repository,
    )

    assert result["method_id"] == "shapley_exact"
    assert result["fixture_count"] == 5
    assert result["boundary_fixture_count"] == 1
    assert result["all_close"] is True
    assert result["maximum_absolute_error"] <= 1e-12
    assert result["maximum_fixture_oracle_error"] <= 1e-12
    assert result["source_execution"] == "unchanged_upstream_files_with_import_shims"
    assert set(result["executed_source_files"]) == {
        "external_source",
        "external_dependency_abstract_approximation",
        "external_dependency_experiment_storage",
        "external_dependency_utils",
    }
    boundary = result["boundary_comparisons"]
    assert len(boundary) == 1
    assert boundary[0]["case_id"] == "nonzero-empty-coalition"
    assert boundary[0]["status"] == "expected_semantic_boundary"
    assert boundary[0]["matches_declared_difference"] is True
    assert boundary[0]["declared_difference"] == (
        "upstream ground-truth enumerator assumes v(empty)=0 and omits the "
        "empty-coalition subtraction"
    )
    assert boundary[0]["maximum_absolute_difference"] > 1.0

    record = evidence / "external_svarm_exact_shapley_v1.json"
    audit = audit_external_implementation_records(
        (record.relative_to(repository).as_posix(),),
        repository,
        expected_method_ids={"shapley_exact"},
        minimum_records=1,
        minimum_fixtures=3,
    )
    assert audit["passed"] is True
    assert audit["official_upstream_count"] == 0

    stored = json.loads(
        (evidence / "external_svarm_exact_shapley_results_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == result


def test_svarm_exact_shapley_crosscheck_rejects_source_drift(tmp_path: Path) -> None:
    from datamechbench.external_shapley_validation import (
        build_svarm_exact_shapley_validation,
    )

    repository = tmp_path / "repo"
    source_root = REPOSITORY_ROOT / "benchmark/external/svarm_exact_snapshot"
    external = repository / "benchmark/external/svarm_official"
    external.mkdir(parents=True)
    source_files = (
        "ApproxMethods/GroundTruth/ExhaustiveSearch.py",
        "ApproxMethods/AbstractApproxMethod.py",
        "Experiment/ExperimentData.py",
        "utils/utils.py",
        "LICENSE",
        "exact_shapley_fixtures.json",
    )
    for name in source_files:
        destination = external / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / name, destination)
    source = external / "ApproxMethods/GroundTruth/ExhaustiveSearch.py"
    source.write_text(source.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    runner = repository / "benchmark/scripts/run_external_shapley_validation.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# fixture runner\n", encoding="utf-8")

    try:
        build_svarm_exact_shapley_validation(
            external_directory=external,
            fixture_path=external / "exact_shapley_fixtures.json",
            runner_path=runner,
            output_directory=repository / "benchmark/evidence",
            repository_root=repository,
        )
    except ValueError as exc:
        assert str(exc) == "pinned S-SVARM source hash mismatch: ExhaustiveSearch.py"
    else:
        raise AssertionError("source drift was not rejected")
