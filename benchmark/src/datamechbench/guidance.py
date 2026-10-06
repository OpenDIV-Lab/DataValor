"""Human-readable metric and leaderboard interpretation artifacts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .expectations import load_metric_definitions
from .models import BenchmarkResult
from .provenance import load_provenance


def write_guidance_artifacts(
    results: Iterable[BenchmarkResult], output_dir: str | Path
) -> tuple[Path, Path, Path]:
    materialized = tuple(results)
    destination = Path(output_dir)
    metrics = load_metric_definitions()

    cards = destination / "metric_cards.md"
    lines = ["# Metric Cards", "", "Metrics rank methods only inside a compatible setting; guardrails and costs are never folded into an arbitrary weighted score.", ""]
    for metric in metrics.values():
        bounds = "unbounded" if metric.valid_range is None else f"[{metric.valid_range[0]}, {metric.valid_range[1]}]"
        lines.extend([
            f"## {metric.display_name} (`{metric.metric_id}`)", "",
            f"- Question answered: {metric.question_answered}",
            f"- Interpretation: {metric.interpretation}",
            f"- Direction / role: {metric.direction} / {metric.ranking_role}",
            f"- Good value: {metric.good_value}",
            f"- Bad value: {metric.bad_value}",
            f"- Valid range / scale: {bounds}; {metric.scale_notes}",
            f"- Applicability: {metric.applicability}",
            f"- Failure modes: {'; '.join(metric.failure_modes)}",
            f"- Paper protocol: {metric.paper_protocol}",
            f"- Companion metrics: {', '.join(metric.companion_metrics) or 'none declared'}", "",
        ])
    cards.write_text("\n".join(lines) + "\n", encoding="utf-8")

    guide = destination / "leaderboard_guide.md"
    guide.write_text(
        """# Leaderboard Guide

## Reading a row

- **Raw rank** orders every method with an applicable primary metric.
- **Qualified rank** requires complete primary-metric coverage over every case on which that method was scheduled. This prevents a method from winning by returning values only on easy cases.
- **Constraint-qualified rank** additionally requires every applicable observable mechanism guardrail to pass. A missing guardrail is `not_auditable`, never an implicit pass.
- `coverage_ratio = ranked case count / eligible case count`; inspect the retained reason whenever qualified rank is blank.
- Confidence intervals summarize case-level macro means: seeds are averaged inside a case before cases receive equal weight.

## Four distinct claims

1. A **performance claim** comes from a setting-specific qualified rank and primary metric.
2. A **constraint claim** comes from the mechanism profile and its pessimistically aggregated guardrails.
3. A **difference claim** comes from paired common-case bootstrap intervals plus Holm-adjusted Wilcoxon tests; non-significance is not equivalence.
4. A **transfer claim** reports what changes under one named assumption relaxation. Transfer deltas are diagnostics and are never folded into a global score.

## Decision rules

Do not compare ranks across settings: each setting answers a different mechanism-design question and can use a different primary metric or direction. First select the decision-relevant setting, then use qualified rank, then inspect guardrails (truthfulness stress, IR, budget balance, false trades) and cost metrics. A paper claim marked `not_met` is retained evidence, not an automatic exclusion and not a theoretical refutation.

## Fidelity

`paper_exact` and `official_adapter` are the strongest fidelity labels. `paper_variant` rows remain useful comparisons but their declared deviations must be read in `method_sources.md`. Deferred candidates are recorded in `catalog/research_candidates.yaml` and are not silently presented as implemented methods.
""",
        encoding="utf-8",
    )

    matrix = destination / "method_setting_matrix.csv"
    catalog = load_provenance()
    settings = sorted({str(row.metadata.get("benchmark_setting", "")) for row in materialized if row.metadata.get("benchmark_setting")})
    observed = {(row.method_id, str(row.metadata.get("benchmark_setting", ""))) for row in materialized}
    with matrix.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("track", "method_id", "family_id", "provenance_kind", *settings))
        writer.writeheader()
        for record in sorted(catalog.mechanisms.values(), key=lambda item: (item.track, item.method_id)):
            writer.writerow({
                "track": record.track,
                "method_id": record.method_id,
                "family_id": record.family_id,
                "provenance_kind": record.provenance_kind,
                **{setting: "evaluated" if (record.method_id, setting) in observed else "not_scheduled" for setting in settings},
            })
    return cards, guide, matrix


__all__ = ["write_guidance_artifacts"]
