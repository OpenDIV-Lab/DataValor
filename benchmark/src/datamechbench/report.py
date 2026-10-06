"""Standard-library result writers for portable benchmark artifacts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .evidence_report import write_evidence_artifacts
from .expectations import (
    ExpectationSpec,
    evaluate_expectations,
    load_expectations,
)
from .guidance import write_guidance_artifacts
from .leaderboard import (
    PRIMARY_METRICS,
    SETTING_PRIMARY_METRICS,
    LeaderboardRow,
    summarize_leaderboard,
    summarize_metrics,
)
from .metrics import MetricValue
from .models import BenchmarkResult
from .provenance import load_provenance

SETTING_GUIDANCE = {
    "V-AXIOM": (
        "How closely does a valuation solution satisfy exact cooperative-game reference behavior?",
        "Finite analytic games test axioms; they do not establish downstream ML usefulness.",
    ),
    "V-CORRUPTION": (
        "Can the valuation identify owners containing controlled label or feature corruption?",
        "Synthetic corruption labels measure detection, not fairness or causal responsibility.",
    ),
    "V-CONTRIBUTION": (
        "Do owner values track held-out utility lost when that owner is removed?",
        "Deletion effects depend on the fixed model, split, and owner partition.",
    ),
    "V-UTILITY-NOISE": (
        "Are rankings stable when coalition utility evaluations are noisy?",
        "Gaussian utility noise is a controlled stressor, not a universal deployment noise model.",
    ),
    "V-REPLICATION-ROBUSTNESS": (
        "Can an owner gain reward share by copying rows without adding information?",
        "Exact-copy factors 1/2/4 do not cover adaptive or strongly perturbed replication.",
    ),
    "P-ADDITIVE": (
        "How efficiently does a mechanism procure additive public value under a hard budget?",
        "Public additive values omit complementarity and hidden data quality.",
    ),
    "P-SUBMODULAR": (
        "How efficiently and safely does a mechanism procure diminishing-return coverage value?",
        "The weighted-coverage oracle is monotone submodular but remains a benchmark construction.",
    ),
    "P-ML-ACQUISITION": (
        "What utility does procurement realize when value is measured through a fixed ML task?",
        "Measured validation utility need not satisfy the monotone-submodular assumptions of paper mechanisms.",
    ),
    "P-MARKET-CONCENTRATION": (
        "How does welfare change as one seller accounts for more of the budget-feasible optimum?",
        "Largest-singleton share is a finite proxy for the large-market assumption, not an asymptotic proof.",
    ),
    "T-BILATERAL": (
        "How do single-sale pricing rules trade off allocation, surplus, and incentives?",
        "Known synthetic priors are controlled models rather than observed data-market bids.",
    ),
    "T-DOUBLE": (
        "How much efficient gain from trade survives two-sided clearing constraints?",
        "Balanced single-unit markets omit multi-unit and combinatorial demand.",
    ),
    "T-CORRELATED": (
        "How do clearing mechanisms transfer when independent private values are relaxed?",
        "A common-component generator represents one form of correlation only.",
    ),
    "T-NO-TRADE": (
        "Does a mechanism avoid inefficient trades when every buyer value is below every seller cost?",
        "This is a safety edge case and cannot rank positive-trade efficiency.",
    ),
    "T-MARKET-THICKNESS": (
        "Does relative efficiency loss shrink as the efficient trade count grows?",
        "Controlled margins isolate thickness but do not represent strategic entry or correlated arrivals.",
    ),
}


def write_jsonl(results: Iterable[BenchmarkResult], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return target


def load_jsonl_results(path: str | Path) -> tuple[BenchmarkResult, ...]:
    """Load portable raw results and restore structured metric values."""

    results = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"non-standard numeric constant {value}")
                    ),
                )
                metrics = {
                    name: (
                        MetricValue(**value)
                        if isinstance(value, dict)
                        and {"value", "applicable", "reason"} <= set(value)
                        else value
                    )
                    for name, value in dict(raw.get("metrics", {})).items()
                }
                results.append(BenchmarkResult(**{**raw, "metrics": metrics}))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid benchmark result at line {line_number}: {exc}") from exc
    return tuple(results)


def _metric_parts(metric) -> tuple[object, bool | str, str]:
    if isinstance(metric, MetricValue):
        value = metric.value
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value, metric.applicable, metric.reason or ""
    return metric, True, ""


def write_track_csvs(results: Iterable[BenchmarkResult], output_dir: str | Path) -> tuple[Path, ...]:
    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    fields = (
        "run_id",
        "method_id",
        "method_role",
        "case_id",
        "seed",
        "status",
        "runtime_seconds",
        "metric",
        "value",
        "applicable",
        "reason",
        "error",
    )
    for track in ("valuation", "procurement", "trading"):
        target = destination / f"summary_{track}.csv"
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for result in materialized:
                if result.track != track:
                    continue
                metrics = result.metrics or {"": MetricValue.na(result.error or result.status)}
                for name, metric in metrics.items():
                    value, applicable, reason = _metric_parts(metric)
                    writer.writerow(
                        {
                            "run_id": result.run_id,
                            "method_id": result.method_id,
                            "method_role": result.metadata.get("method_role", ""),
                            "case_id": result.case_id,
                            "seed": result.seed,
                            "status": result.status,
                            "runtime_seconds": result.runtime_seconds,
                            "metric": name,
                            "value": value,
                            "applicable": applicable,
                            "reason": reason,
                            "error": result.error or "",
                        }
                    )
        paths.append(target)
    return tuple(paths)


def _write_dict_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_leaderboard_csvs(
    results: Iterable[BenchmarkResult], output_dir: str | Path
) -> tuple[Path, ...]:
    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    leaderboard_fields = tuple(LeaderboardRow.__dataclass_fields__)

    main = summarize_leaderboard(materialized, include_pilots=False)
    main_path = _write_dict_csv(
        destination / "leaderboard_main.csv",
        [row.to_dict() for row in main],
        leaderboard_fields,
    )

    settings = sorted(
        {
            str(result.metadata["benchmark_setting"])
            for result in materialized
            if "benchmark_setting" in result.metadata
        }
    )
    setting_rows = []
    for setting in settings:
        setting_rows.extend(
            summarize_leaderboard(
                materialized, include_pilots=False, setting=setting
            )
        )
        setting_rows.extend(
            summarize_leaderboard(
                materialized,
                include_pilots=True,
                setting=setting,
                pilot_only=True,
            )
        )
    settings_path = _write_dict_csv(
        destination / "leaderboard_settings.csv",
        [row.to_dict() for row in setting_rows],
        leaderboard_fields,
    )

    statistics = summarize_metrics(materialized)
    statistic_fields = tuple(statistics[0].__dataclass_fields__) if statistics else (
        "track",
        "setting",
        "scope",
        "family_id",
        "method_id",
        "metric",
        "mean",
        "std",
        "ci95_low",
        "ci95_high",
        "case_count",
        "observation_count",
    )
    statistics_path = _write_dict_csv(
        destination / "metric_statistics.csv",
        [row.to_dict() for row in statistics],
        statistic_fields,
    )
    return main_path, settings_path, statistics_path


def write_research_artifacts(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    expectations: Iterable[ExpectationSpec] | None = None,
    config_path: str | Path | None = None,
) -> tuple[Path, ...]:
    """Write provenance, paper-view, setting, claim, and property artifacts."""

    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    leaderboard_fields = tuple(LeaderboardRow.__dataclass_fields__)
    paper_main = summarize_leaderboard(
        materialized, include_pilots=False, view="paper"
    )
    paper_main_path = _write_dict_csv(
        destination / "leaderboard_paper_main.csv",
        [row.to_dict() for row in paper_main],
        leaderboard_fields,
    )
    settings = sorted(
        {
            str(result.metadata["benchmark_setting"])
            for result in materialized
            if "benchmark_setting" in result.metadata
        }
    )
    paper_setting_rows = [
        row
        for setting in settings
        for row in summarize_leaderboard(
            materialized,
            include_pilots=False,
            setting=setting,
            view="paper",
        )
    ]
    paper_settings_path = _write_dict_csv(
        destination / "leaderboard_paper_settings.csv",
        [row.to_dict() for row in paper_setting_rows],
        leaderboard_fields,
    )

    catalog = load_provenance()
    source_fields = (
        "method_id",
        "family_id",
        "track",
        "provenance_kind",
        "implementation_kind",
        "algorithm_location",
        "reference_keys",
        "reference_titles",
        "reference_urls",
        "baseline_usage_reference_keys",
        "deviations",
    )
    source_rows = []
    for record in sorted(catalog.mechanisms.values(), key=lambda item: (item.track, item.method_id)):
        source_rows.append(
            {
                "method_id": record.method_id,
                "family_id": record.family_id,
                "track": record.track,
                "provenance_kind": record.provenance_kind,
                "implementation_kind": record.implementation_kind,
                "algorithm_location": record.algorithm_location,
                "reference_keys": ";".join(record.reference_keys),
                "reference_titles": ";".join(ref.title for ref in record.references),
                "reference_urls": ";".join(ref.url for ref in record.references),
                "baseline_usage_reference_keys": ";".join(record.baseline_usage_reference_keys),
                "deviations": ";".join(record.deviations),
            }
        )
    source_csv = _write_dict_csv(destination / "method_sources.csv", source_rows, source_fields)
    source_md = destination / "method_sources.md"
    source_lines = [
        "# Method Sources and Fidelity",
        "",
        "`paper_variant` means the implementation is retained for comparison but is not asserted to be an exact reproduction.",
        "",
        "| method | track | family | provenance | algorithm/source location | references | deviations |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in sorted(catalog.mechanisms.values(), key=lambda item: (item.track, item.method_id)):
        references = "<br>".join(
            f"[{ref.title}]({ref.url})" for ref in record.references
        )
        source_lines.append(
            f"| `{record.method_id}` | {record.track} | `{record.family_id}` | "
            f"{record.provenance_kind} | {record.algorithm_location} | {references} | "
            f"{'<br>'.join(record.deviations) or 'None declared'} |"
        )
    source_md.write_text("\n".join(source_lines) + "\n", encoding="utf-8")

    claim_specs = tuple(expectations) if expectations is not None else load_expectations()
    claim_rows: list[dict[str, object]] = []
    for result in materialized:
        case_context = {
            "assumptions": result.metadata.get("case_assumptions", ()),
        }
        for evaluation in evaluate_expectations(result, case_context, claim_specs):
            claim_rows.append(
                {
                    "run_id": result.run_id,
                    "track": result.track,
                    "method_id": result.method_id,
                    "family_id": result.metadata.get("method_family", result.method_id),
                    "case_id": result.case_id,
                    "setting": result.metadata.get("benchmark_setting", ""),
                    **asdict(evaluation),
                    "missing_assumptions": ";".join(evaluation.missing_assumptions),
                }
            )
    claim_fields = (
        "run_id", "track", "method_id", "family_id", "case_id", "setting",
        "expectation_id", "status", "observed", "target", "comparison_observed",
        "missing_assumptions", "reason",
    )
    expectation_path = _write_dict_csv(
        destination / "expectation_results.csv", claim_rows, claim_fields
    )

    setting_path = destination / "setting_cards.md"
    setting_lines = ["# Setting Cards", ""]
    for setting in settings:
        rows = [
            result
            for result in materialized
            if result.metadata.get("benchmark_setting") == setting
        ]
        assumptions = sorted(
            {
                assumption
                for result in rows
                for assumption in result.metadata.get("case_assumptions", ())
            }
        )
        provenance_counts = Counter(
            str(result.metadata.get("provenance_kind", "unknown"))
            for result in rows
        )
        tracks = sorted({result.track for result in rows})
        track = tracks[0] if len(tracks) == 1 else ""
        metric, direction = SETTING_PRIMARY_METRICS.get(
            setting,
            (PRIMARY_METRICS.get(track, "setting-specific"), "maximize"),
        )
        question, boundary = SETTING_GUIDANCE.get(
            setting,
            (
                "What does this declared mechanism cohort reveal on its setting-specific objective?",
                "Interpret only within the declared case cohort and assumptions.",
            ),
        )
        setting_lines.extend(
            [
                f"## {setting}",
                "",
                f"- Decision question: {question}",
                f"- Primary metric: `{metric}` ({direction})",
                f"- Interpretation boundary: {boundary}",
                f"- Tracks: {', '.join(tracks)}",
                f"- Cases: {len({result.case_id for result in rows})}",
                f"- Methods: {len({result.method_id for result in rows})}",
                f"- Assumptions represented: {', '.join(assumptions) or 'none declared'}",
                "- Provenance coverage: " + ", ".join(
                    f"{key}={value}" for key, value in sorted(provenance_counts.items())
                ),
                "",
            ]
        )
    setting_path.write_text("\n".join(setting_lines) + "\n", encoding="utf-8")

    property_names = {
        "efficiency_residual", "dummy_violation", "symmetry_gap",
        "least_core_max_violation", "replication_gain", "split_payoff_change",
        "budget_violation", "seller_ir_violation_count",
        "allocation_monotonicity_violation", "critical_payment_gap",
        "individual_rationality", "weak_budget_balance", "strong_budget_balance",
        "trade_count_loss", "false_trade_count", "max_deviation_gain",
    }
    property_rows = []
    for result in materialized:
        for metric_name, metric in result.metrics.items():
            if metric_name not in property_names:
                continue
            value, applicable, reason = _metric_parts(metric)
            property_rows.append(
                {
                    "run_id": result.run_id,
                    "track": result.track,
                    "method_id": result.method_id,
                    "case_id": result.case_id,
                    "setting": result.metadata.get("benchmark_setting", ""),
                    "metric": metric_name,
                    "value": value,
                    "applicable": applicable,
                    "reason": reason,
                }
            )
    property_fields = (
        "run_id", "track", "method_id", "case_id", "setting", "metric",
        "value", "applicable", "reason",
    )
    property_path = _write_dict_csv(
        destination / "property_results.csv", property_rows, property_fields
    )
    guidance_paths = write_guidance_artifacts(materialized, destination)
    evidence_paths = write_evidence_artifacts(
        materialized,
        destination,
        config_path=config_path,
    )
    return (
        paper_main_path,
        paper_settings_path,
        source_csv,
        source_md,
        expectation_path,
        setting_path,
        property_path,
        *guidance_paths,
        *evidence_paths,
    )


def _format_number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.4f}"


def _append_leaderboard(lines: list[str], title: str, rows: Iterable[LeaderboardRow]) -> None:
    materialized = tuple(rows)
    lines.extend(
        [
            f"### {title}",
            "",
            "| track | qualified rank | raw rank | family | implementation | metric | mean | 95% CI | coverage | cases | observations |",
            "|---|---:|---:|---|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for row in materialized:
        rank = str(row.qualified_rank) if row.qualified_rank is not None else "N/A"
        raw_rank = str(row.raw_rank) if row.raw_rank is not None else "N/A"
        interval = f"[{_format_number(row.ci95_low)}, {_format_number(row.ci95_high)}]"
        lines.append(
            f"| {row.track} | {rank} | {raw_rank} | {row.family_id} | {row.method_id} | "
            f"{row.primary_metric} | {_format_number(row.mean)} | {interval} | "
            f"{row.coverage_ratio:.1%} | {row.case_count}/{row.eligible_case_count} | {row.observation_count} |"
        )
    if not materialized:
        lines.append("| _none_ |  |  |  |  |  |  |  |  |  |  |")
    lines.append("")


def write_markdown_report(results: Iterable[BenchmarkResult], path: str | Path) -> Path:
    materialized = tuple(results)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Data Mechanism Benchmark Report", ""]
    status_counts = Counter(result.status for result in materialized)
    lines.extend(
        [
            "## Run summary",
            "",
            f"- completed: {status_counts['completed']}",
            f"- skipped: {status_counts['skipped']}",
            f"- failed: {status_counts['failed']}",
            "",
        ]
    )
    lines.extend(
        [
            "## Coverage summary",
            "",
            "| track | run methods | families | settings |",
            "|---|---:|---:|---:|",
        ]
    )
    for track in ("valuation", "procurement", "trading"):
        rows = [result for result in materialized if result.track == track]
        methods = {result.method_id for result in rows}
        families = {
            result.metadata.get("method_family", result.method_id) for result in rows
        }
        settings = {
            result.metadata.get("benchmark_setting", result.metadata.get("case_type", ""))
            for result in rows
        }
        settings.discard("")
        lines.append(
            f"| {track} | {len(methods)} | {len(families)} | {len(settings)} |"
        )
    lines.append("")
    lines.extend(["## Main leaderboards", ""])
    _append_leaderboard(
        lines,
        "Stable cases (pilots excluded)",
        summarize_leaderboard(materialized, include_pilots=False),
    )
    _append_leaderboard(
        lines,
        "Paper/project mechanisms (common baselines excluded)",
        summarize_leaderboard(
            materialized, include_pilots=False, view="paper"
        ),
    )

    settings = sorted(
        {
            str(result.metadata["benchmark_setting"])
            for result in materialized
            if "benchmark_setting" in result.metadata
        }
    )
    lines.extend(["## Selected setting leaderboards", ""])
    for setting in settings:
        _append_leaderboard(
            lines,
            setting,
            summarize_leaderboard(
                materialized, include_pilots=False, setting=setting
            ),
        )

    lines.extend(["## Pilot evidence", ""])
    for setting in settings:
        pilot_rows = summarize_leaderboard(
            materialized,
            include_pilots=True,
            setting=setting,
            pilot_only=True,
        )
        if pilot_rows:
            _append_leaderboard(lines, setting, pilot_rows)

    diagnostic_names = {
        "replication_gain",
        "kendall_stability",
        "budget_violation",
        "seller_ir_violation_count",
        "individual_rationality",
        "weak_budget_balance",
        "max_deviation_gain",
        "wall_runtime_seconds",
    }
    lines.extend(
        [
            "## Constraint and audit statistics",
            "",
            "Boolean means are empirical satisfaction/violation rates. These diagnostics are not folded into rank.",
            "",
            "| track | setting | scope | family | method | metric | mean | 95% CI | cases |",
            "|---|---|---|---|---|---|---:|---|---:|",
        ]
    )
    diagnostics = [
        row for row in summarize_metrics(materialized) if row.metric in diagnostic_names
    ]
    for row in diagnostics:
        lines.append(
            f"| {row.track} | {row.setting} | {row.scope} | {row.family_id} | "
            f"{row.method_id} | {row.metric} | {row.mean:.4f} | "
            f"[{row.ci95_low:.4f}, {row.ci95_high:.4f}] | {row.case_count} |"
        )
    if not diagnostics:
        lines.append("| _none_ |  |  |  |  |  |  |  |  |")
    lines.append("")

    for track in ("valuation", "procurement", "trading"):
        track_results = [result for result in materialized if result.track == track]
        lines.extend([f"## {track.title()}", "", "| method | role | completed | skipped | failed |", "|---|---|---:|---:|---:|"])
        for method_id in sorted({result.method_id for result in track_results}):
            rows = [result for result in track_results if result.method_id == method_id]
            role = rows[0].metadata.get("method_role", "")
            counts = Counter(row.status for row in rows)
            label = f"{role} (reference only)" if role == "oracle" else role
            lines.append(
                f"| {method_id} | {label} | {counts['completed']} | {counts['skipped']} | {counts['failed']} |"
            )
        if not track_results:
            lines.append("| _none_ |  | 0 | 0 | 0 |")
        lines.append("")

    na_reasons = Counter()
    for result in materialized:
        if result.error:
            na_reasons[result.error] += 1
        for metric in result.metrics.values():
            if isinstance(metric, MetricValue) and not metric.applicable:
                na_reasons[metric.reason or "unspecified"] += 1
    lines.extend(["## N/A and retained errors", "", "| reason | count |", "|---|---:|"])
    for reason, count in sorted(na_reasons.items()):
        lines.append(f"| `{reason}` | {count} |")
    if not na_reasons:
        lines.append("| _none_ | 0 |")
    lines.append("")
    lines.append("Oracle rows are labeled as references and are not ordinary leaderboard averages.")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


__all__ = [
    "load_jsonl_results",
    "write_jsonl",
    "write_leaderboard_csvs",
    "write_markdown_report",
    "write_track_csvs",
    "write_research_artifacts",
]
