from __future__ import annotations

import json
from pathlib import Path

from datamechbench.cli import main
from datamechbench.elr_evidence_report import write_elr_evidence_report
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.report import write_jsonl


def test_report_discloses_completed_failed_skipped_and_all_criteria(tmp_path: Path) -> None:
    common = {
        "setting_id": "cell-a",
        "budget": 64,
        "primary_task": True,
        "estimand": "ordinary_shapley",
        "modality": "tabular",
        "model_family": "tree_ensemble",
        "fidelity_mechanism": "ensemble_width",
    }
    rows = [
        BenchmarkResult(
            "ok-elr", "valuation", "shapley_exact_low_residual", "cell-a", 0,
            "completed", {"score_mae": MetricValue(0.5)}, 0.1, metadata=common,
        ),
        BenchmarkResult(
            "ok-base", "valuation", "shapiq_svarm", "cell-a", 0,
            "completed", {"score_mae": MetricValue(1.0)}, 0.1, metadata=common,
        ),
        BenchmarkResult(
            "failed", "valuation", "shapiq_kernel_shap", "cell-a", 0,
            "failed", {}, 0.1, error="boom", metadata=common,
        ),
        BenchmarkResult(
            "skipped", "valuation", "asss_a", "cell-a", 0,
            "skipped", {}, 0.0, error="official_implementation_unavailable", metadata=common,
        ),
    ]
    paths = write_elr_evidence_report(
        rows,
        tmp_path,
        declared_cells=("cell-a",),
        declared_budgets=(64,),
        bootstrap_samples=50,
    )
    markdown = paths.markdown.read_text()
    payload = json.loads(paths.json.read_text())
    assert "failed" in markdown and "skipped" in markdown
    assert "boom" in markdown and "official_implementation_unavailable" in markdown
    assert len(payload["criteria"]) == 6
    assert payload["status_counts"] == {"completed": 2, "failed": 1, "skipped": 1}

    raw = write_jsonl(rows, tmp_path / "raw.jsonl")
    cli_output = tmp_path / "cli"
    assert main(["validate", "--results", str(raw)]) == 0
    assert main(["summarize", "--results", str(raw), "--output", str(cli_output)]) == 0
    assert main(["evidence-report", "--results", str(raw), "--output", str(cli_output)]) == 0
    assert (cli_output / "elr_summary.json").is_file()
    assert (cli_output / "elr_evidence.md").is_file()
