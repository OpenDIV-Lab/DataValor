from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from datamechbench.cli import main
from datamechbench.models import BenchmarkResult
from datamechbench.report import write_jsonl
from datamechbench.runner import build_cases, load_config


def test_cli_analytic_smoke_writes_all_artifacts(tmp_path):
    config = tmp_path / "smoke.yaml"
    output = tmp_path / "results"
    config.write_text(
        f"""
name: smoke
output_dir: {output}
seeds: [0]
strategic_audit: false
cases:
  valuation: [C-add]
  procurement: [P-C-add-b30]
  trading: []
methods:
  valuation:
    - id: shapley_exact
  procurement:
    - id: budget_optimum
  trading: []
""".strip(),
        encoding="utf-8",
    )

    assert main(["run", "--config", str(config)]) == 0
    expected = (
        "raw_results.jsonl",
        "summary_valuation.csv",
        "summary_procurement.csv",
        "summary_trading.csv",
        "leaderboard_main.csv",
        "leaderboard_settings.csv",
        "metric_statistics.csv",
        "report.md",
        "benchmark_manifest.json",
        "benchmark_card.md",
        "paper_evidence.md",
    )
    for name in expected:
        path = output / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name


def test_all_compatible_cli_runs_every_analytic_family_without_failures(tmp_path):
    config = tmp_path / "all.yaml"
    output = tmp_path / "all-results"
    config.write_text(
        f"""
name: all-compatible-smoke
output_dir: {output}
seeds: [0]
strategic_audit: false
cases:
  valuation: [C-add]
  procurement: [P-C-add-b50]
  trading: [S5-single-sale]
methods:
  valuation: [all_compatible]
  procurement: [all_compatible]
  trading: [all_compatible]
""".strip(),
        encoding="utf-8",
    )

    assert main(["run", "--config", str(config)]) == 0
    rows = (output / "raw_results.jsonl").read_text(encoding="utf-8").splitlines()
    assert rows
    assert all('"status": "failed"' not in row for row in rows)


def test_default_config_uses_automatic_compatible_expansion():
    config = load_config("benchmark/configs/mvp.yaml")

    assert set(config.methods) == {"valuation", "procurement", "trading"}
    assert all("all_compatible" in config.methods[track] for track in config.methods)


def test_full_config_selects_every_case_and_ten_seeds():
    config = load_config("benchmark/configs/full.yaml")
    cases = build_cases(seed=42)

    assert config.seeds == tuple(range(10))
    assert config.strategic_audit is True
    assert all("all_compatible" in config.methods[track] for track in config.methods)
    for track, track_cases in cases.items():
        assert set(config.case_ids[track]) == {case.case_id for case in track_cases}


def test_validate_submission_cli_writes_report_and_exit_code(tmp_path, capsys):
    package = tmp_path / "submission"
    package.mkdir()
    (package / "submission.yaml").write_text(
        yaml.safe_dump({"submitter": "incomplete"}), encoding="utf-8"
    )
    (package / "results.jsonl").write_text("", encoding="utf-8")

    assert main(["validate-submission", "--submission", str(package)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert (package / "submission_validation.json").is_file()


def test_validate_submission_cli_can_write_report_outside_package(tmp_path, capsys):
    repository = Path(__file__).resolve().parents[2]
    package = tmp_path / "submission"
    shutil.copytree(repository / "benchmark" / "submission_template", package)
    output = tmp_path / "validation.json"

    assert main([
        "validate-submission",
        "--submission", str(package),
        "--output", str(output),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert output.is_file()
    assert not (package / "submission_validation.json").exists()


def test_validate_case_submission_cli_writes_fail_closed_report(tmp_path, capsys):
    package = tmp_path / "case-package"
    package.mkdir()
    output = tmp_path / "case-validation.json"

    assert main([
        "validate-case-submission",
        "--submission", str(package),
        "--output", str(output),
    ]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["review_eligible"] is False
    assert payload["evidence_scope"] == "open_development_only"
    assert output.is_file()


def test_kdd_readiness_cli_writes_fail_closed_reports(tmp_path, capsys):
    results_path = tmp_path / "raw_results.jsonl"
    write_jsonl(
        (
            BenchmarkResult(
                run_id="partial",
                track="valuation",
                method_id="shapley_exact",
                case_id="VREP-test",
                seed=0,
                status="completed",
                metrics={"replication_rank_gain": 0.0},
                runtime_seconds=0.01,
                metadata={"benchmark_setting": "V-REPLICATION-ROBUSTNESS"},
            ),
        ),
        results_path,
    )
    output = tmp_path / "audit"
    repository = Path(__file__).resolve().parents[2]

    assert main([
        "kdd-readiness",
        "--results", str(results_path),
        "--target", str(repository / "benchmark" / "catalog" / "kdd_submission.yaml"),
        "--output", str(output),
        "--repository-root", str(repository),
        "--post-release-evidence", str(tmp_path / "missing-post-release.yaml"),
    ]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["failed_gate_count"] > 0
    assert (output / "kdd_readiness.json").is_file()
    markdown = (output / "kdd_readiness.md").read_text(encoding="utf-8")
    assert "KDD 2027 Datasets & Benchmarks Readiness" in markdown
    assert "NOT READY" in markdown
