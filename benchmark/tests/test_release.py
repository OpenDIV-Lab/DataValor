from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

from datamechbench.models import BenchmarkResult
from datamechbench.release import load_release_metadata, write_release_artifacts


def test_package_version_matches_benchmark_release_catalog() -> None:
    repository = Path(__file__).resolve().parents[2]
    package = tomllib.loads(
        (repository / "benchmark" / "pyproject.toml").read_text(encoding="utf-8")
    )
    release = load_release_metadata(
        repository / "benchmark" / "catalog" / "benchmark_release.yaml"
    )

    assert package["project"]["version"] == release["benchmark_version"] == "0.3.0"


def _result(value: float) -> BenchmarkResult:
    return BenchmarkResult(
        run_id="run",
        track="valuation",
        method_id="shapley_exact",
        case_id="C-add",
        seed=0,
        status="completed",
        metrics={"score_spearman": value},
        runtime_seconds=0.01,
        metadata={
            "method_family": "shapley",
            "benchmark_setting": "valuation_game",
        },
    )


def _manifest(tmp_path: Path, value: float, *, with_config: bool = True) -> dict:
    output = tmp_path / str(value).replace(".", "-")
    output.mkdir()
    (output / "raw_results.jsonl").write_text("source\n", encoding="utf-8")
    (output / "constraint_leaderboard.csv").write_text("a\n1\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    if with_config:
        config.write_text("name: test\n", encoding="utf-8")
    paths = write_release_artifacts((_result(value),), output, config_path=config if with_config else None)
    assert {path.name for path in paths} == {
        "benchmark_manifest.json",
        "benchmark_card.md",
        "paper_evidence.md",
    }
    return json.loads((output / "benchmark_manifest.json").read_text(encoding="utf-8"))


def test_release_manifest_records_environment_counts_digests_and_artifacts(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, 0.8)

    assert manifest["benchmark"]["version"]
    assert {"python", "platform", "numpy", "scipy", "scikit-learn", "datamechbench"} <= set(manifest["environment"])
    assert manifest["counts"]["results"] == 1
    assert sum(manifest["counts"]["statuses"].values()) == 1
    assert manifest["inputs"]["run_config"]["status"] == "available"
    assert len(manifest["inputs"]["result_payload"]["sha256"]) == 64
    assert manifest["inputs"]["benchmark_source"]["status"] == "available"
    assert manifest["inputs"]["benchmark_source"]["file_count"] > 0
    assert len(manifest["inputs"]["benchmark_source"]["sha256"]) == 64
    assert manifest["inputs"]["kdd_submission"]["status"] == "available"
    assert len(manifest["inputs"]["kdd_submission"]["sha256"]) == 64
    assert manifest["inputs"]["case_bank_development_v1"]["status"] == "available"
    assert len(manifest["inputs"]["case_bank_development_v1"]["sha256"]) == 64
    for artifact in manifest["artifacts"]:
        assert (tmp_path / "0-8" / artifact["path"]).is_file()
        assert len(artifact["sha256"]) == 64


def test_result_digest_changes_with_source_input_and_missing_config_is_explicit(tmp_path: Path) -> None:
    first = _manifest(tmp_path, 0.8)
    second = _manifest(tmp_path, 0.7, with_config=False)

    assert first["inputs"]["result_payload"]["sha256"] != second["inputs"]["result_payload"]["sha256"]
    assert second["inputs"]["run_config"] == {"status": "missing", "sha256": None, "path": None}
