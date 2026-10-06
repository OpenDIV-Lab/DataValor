"""Machine-generated ELR-VRDS evidence report with complete run disclosure."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .elr_analysis import analyze_elr_results
from .models import BenchmarkResult


@dataclass(frozen=True)
class EvidenceReportPaths:
    markdown: Path
    json: Path


def write_elr_evidence_report(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    declared_cells: Iterable[str],
    declared_budgets: Iterable[float],
    bootstrap_samples: int = 10_000,
) -> EvidenceReportPaths:
    materialized = tuple(results)
    analysis = analyze_elr_results(
        materialized,
        declared_cells=declared_cells,
        declared_budgets=declared_budgets,
        bootstrap_samples=bootstrap_samples,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    status_counts = dict(sorted(Counter(row.status for row in materialized).items()))
    payload = {**analysis.to_dict(), "status_counts": status_counts}
    json_path = destination / "elr_evidence.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines = [
        "# ELR-VRDS evidence report",
        "",
        "This file is generated from raw results; no result numbers are manually entered.",
        "",
        "## Pre-registered criteria",
        "",
    ]
    for criterion in analysis.criteria:
        status = "PASS" if criterion.passed else "FAIL"
        lines.append(f"{criterion.criterion}. **{status}** — {criterion.evidence}")
    lines.extend(
        [
            "",
            "## Cell comparisons",
            "",
            "| setting | budget | ELR variant | strongest baseline | ELR median MAE | baseline median MAE | improvement | Holm p | Cliff's delta | outcome |",
            "|---|---:|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for cell in analysis.cells:
        lines.append(
            f"| {cell.setting_id} | {cell.budget:g} | {cell.elr_method_id} | {cell.baseline_id} | "
            f"{cell.median_elr:.6g} | {cell.median_baseline:.6g} | "
            f"{cell.relative_improvement:.1%} | {cell.adjusted_p_value:.4g} | "
            f"{cell.cliffs_delta:.3f} | {cell.outcome} |"
        )
    lines.extend(["", "## Loss disclosure", ""])
    if analysis.losses:
        for loss in analysis.losses:
            lines.append(
                f"- {loss.setting_id} @ {loss.budget:g}: {loss.relative_loss:.1%} loss; "
                f"{loss.explanation}; residual efficiency={loss.residual_efficiency}."
            )
    else:
        lines.append("- No loss greater than 10%.")
    lines.extend(
        [
            "",
            "## Complete run ledger",
            "",
            "| run | method | case | seed | status | error/N/A reason |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for row in sorted(materialized, key=lambda item: item.run_id):
        reasons = [
            str(metric.reason)
            for metric in row.metrics.values()
            if hasattr(metric, "applicable") and not metric.applicable and metric.reason
        ]
        reason = row.error or "; ".join(reasons)
        lines.append(
            f"| {row.run_id} | {row.method_id} | {row.case_id} | {row.seed} | "
            f"{row.status} | {reason or ''} |"
        )
    markdown_path = destination / "elr_evidence.md"
    markdown_path.write_text("\n".join(lines) + "\n")
    return EvidenceReportPaths(markdown_path, json_path)


__all__ = ["EvidenceReportPaths", "write_elr_evidence_report"]
