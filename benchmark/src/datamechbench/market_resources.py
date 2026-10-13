"""Track-native, execution-level resource accounting for market mechanisms."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .metrics import MetricValue
from .models import BenchmarkResult, MarketOutcome, ProcurementInput, TradeInput
from .outcomes import parse_outcome
from .report import load_jsonl_results

RESOURCE_UNITS = {
    "procurement": ("utility_oracle_calls",),
    "trading": ("submitted_reports", "clearing_passes", "randomization_events"),
}
QUALITY_METRICS = {
    "procurement": "oracle_ratio",
    "trading": "gain_from_trade_ratio",
}
OUTPUT_NAMES = ("resources.csv", "summary.json", "report.md")


@dataclass
class UtilityCallCounter:
    utility: Any
    calls: int = 0

    def __call__(self, selected: tuple[str, ...]) -> float:
        self.calls += 1
        return float(self.utility(selected))


@dataclass(frozen=True)
class MarketResourceRow:
    track: str
    method_id: str
    status: str
    quality_metric_id: str
    mean_quality: float | None
    mean_resources: Mapping[str, float]
    block_count: int
    case_count: int
    run_count: int
    reason: str | None = None


@dataclass(frozen=True)
class MarketResourceReport:
    rows: tuple[MarketResourceRow, ...]


def instrument_procurement_input(
    case: ProcurementInput,
) -> tuple[ProcurementInput, UtilityCallCounter]:
    """Return an input whose utility counts only calls made through this wrapper."""

    counter = UtilityCallCounter(case.utility)
    return replace(case, utility=counter), counter


def _resource_mapping(raw: Mapping[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError("resource usage requires non-negative integer units")
        result[key] = value
    if not result:
        raise ValueError("resource usage must be non-empty")
    return result


def attach_resource_usage(
    output: MarketOutcome, usage: Mapping[str, Any]
) -> MarketOutcome:
    """Attach validated resource units without mutating mechanism diagnostics."""

    diagnostics = dict(output.diagnostics)
    diagnostics["resource_usage"] = _resource_mapping(usage)
    return replace(output, diagnostics=diagnostics)


def trading_resource_usage(
    method_id: str, case: TradeInput, output: MarketOutcome
) -> dict[str, int]:
    """Derive algorithm-level events from the executed trading branch."""

    reports = len(case.buyer_ids) + len(case.seller_ids)
    clearing_passes = 2 if method_id in {
        "lottery_muda",
        "vickrey_muda",
        "random_sampling_double",
    } else 1
    randomization_events = 0
    if method_id == "sbba" and output.diagnostics.get(
        "randomized_seller_exclusion"
    ) is True:
        randomization_events = 1
    elif method_id in {"lottery_muda", "vickrey_muda", "random_sampling_double"}:
        # One independently sampled left/right assignment per submitted report.
        randomization_events = reports
        if method_id in {"lottery_muda", "random_sampling_double"}:
            randomization_events += sum(
                str(output.diagnostics.get(key, "")).startswith("excess_")
                and str(output.diagnostics.get(key, "")).endswith("_lottery")
                for key in ("left_branch", "right_branch")
            )
    return {
        "submitted_reports": reports,
        "clearing_passes": clearing_passes,
        "randomization_events": int(randomization_events),
    }


def _metric_number(row: BenchmarkResult, metric_id: str) -> float | None:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        if not raw.applicable:
            return None
        raw = raw.value
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _case_means(
    measurements: list[tuple[str, str, float, Mapping[str, int]]],
    units: tuple[str, ...],
) -> list[tuple[str, str, float, dict[str, float]]]:
    result = []
    for block, case_id in sorted({(row[0], row[1]) for row in measurements}):
        rows = [row for row in measurements if row[0] == block and row[1] == case_id]
        result.append(
            (
                block,
                case_id,
                fmean(row[2] for row in rows),
                {unit: fmean(row[3][unit] for row in rows) for unit in units},
            )
        )
    return result


def analyze_market_resources(
    results: Iterable[BenchmarkResult],
) -> MarketResourceReport:
    """Aggregate seeds within cases and cases within registered blocks."""

    completed = tuple(
        row
        for row in results
        if row.track in RESOURCE_UNITS and row.status == "completed"
    )
    report_rows: list[MarketResourceRow] = []
    for track, method_id in sorted({(row.track, row.method_id) for row in completed}):
        rows = tuple(
            row for row in completed if row.track == track and row.method_id == method_id
        )
        units = RESOURCE_UNITS[track]
        measurements: list[tuple[str, str, float, Mapping[str, int]]] = []
        reason: str | None = None
        for row in rows:
            quality = _metric_number(row, QUALITY_METRICS[track])
            if quality is None:
                reason = "missing_quality_metric"
                break
            block = str(row.metadata.get("independent_block", "")).strip()
            if not block:
                reason = "missing_independent_block"
                break
            try:
                output = parse_outcome(row.track, row.outcome or {})
            except ValueError:
                reason = "invalid_outcome"
                break
            if not isinstance(output, MarketOutcome):
                reason = "invalid_outcome"
                break
            raw_usage = output.diagnostics.get("resource_usage")
            if not isinstance(raw_usage, Mapping):
                reason = "missing_resource_usage"
                break
            try:
                usage = _resource_mapping(raw_usage)
            except ValueError:
                reason = "invalid_resource_usage"
                break
            if set(usage) != set(units):
                reason = "invalid_resource_units"
                break
            measurements.append((block, row.case_id, quality, usage))
        if reason is not None:
            report_rows.append(
                MarketResourceRow(
                    track,
                    method_id,
                    "not_auditable",
                    QUALITY_METRICS[track],
                    None,
                    {},
                    0,
                    0,
                    len(rows),
                    reason,
                )
            )
            continue
        cases = _case_means(measurements, units)
        blocks = sorted({row[0] for row in cases})
        block_quality = [
            fmean(row[2] for row in cases if row[0] == block) for block in blocks
        ]
        block_resources = {
            unit: [
                fmean(row[3][unit] for row in cases if row[0] == block)
                for block in blocks
            ]
            for unit in units
        }
        report_rows.append(
            MarketResourceRow(
                track,
                method_id,
                "auditable",
                QUALITY_METRICS[track],
                fmean(block_quality),
                {unit: fmean(values) for unit, values in block_resources.items()},
                len(blocks),
                len(cases),
                len(rows),
            )
        )
    return MarketResourceReport(tuple(report_rows))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_market_resource_report(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    results_path: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)
    source = Path(results_path)
    if not source.is_absolute():
        source = root / source
    report = analyze_market_resources(load_jsonl_results(source))
    columns = (
        "track",
        "method_id",
        "status",
        "quality_metric_id",
        "mean_quality",
        "mean_resources_json",
        "block_count",
        "case_count",
        "run_count",
        "reason",
    )
    with (output / "resources.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in report.rows:
            writer.writerow(
                {
                    "track": row.track,
                    "method_id": row.method_id,
                    "status": row.status,
                    "quality_metric_id": row.quality_metric_id,
                    "mean_quality": row.mean_quality,
                    "mean_resources_json": json.dumps(
                        dict(row.mean_resources), sort_keys=True, separators=(",", ":")
                    ),
                    "block_count": row.block_count,
                    "case_count": row.case_count,
                    "run_count": row.run_count,
                    "reason": row.reason,
                }
            )
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-market-resource-v1",
        "valid": bool(report.rows),
        "resource_units": {key: list(value) for key, value in RESOURCE_UNITS.items()},
        "row_count": len(report.rows),
        "auditable_counts": {
            track: sum(row.track == track and row.status == "auditable" for row in report.rows)
            for track in RESOURCE_UNITS
        },
        "claim_boundary": (
            "Units are track-native execution measurements. They are not a cross-track "
            "cost score, hardware-normalized complexity, or end-to-end deployment cost."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Market mechanism resource audit",
        "",
        "Track-native units are reported as a vector; no cross-track composite is defined.",
        "",
        "| Track | Method | Quality | Resource vector | Blocks |",
        "|---|---|---:|---|---:|",
    ]
    for row in report.rows:
        quality = "NA" if row.mean_quality is None else f"{row.mean_quality:.6f}"
        resources = (
            ", ".join(f"{key}={value:.3f}" for key, value in row.mean_resources.items())
            if row.mean_resources
            else f"not auditable: {row.reason}"
        )
        lines.append(
            f"| {row.track} | {row.method_id} | {quality} | {resources} | {row.block_count} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "market_resource_report",
        "inputs": [
            {"path": os.path.relpath(source.resolve(), output.resolve()), "sha256": _sha256(source)}
        ],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_market_resource_report(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if manifest.get("schema_version") != "1.0":
        errors.append("invalid_schema_version")
    if manifest.get("manifest_kind") != "market_resource_report":
        errors.append("invalid_manifest_kind")
    input_records = manifest.get("inputs")
    if not isinstance(input_records, list) or len(input_records) != 1:
        errors.append("invalid_inputs")
    else:
        record = input_records[0]
        if not isinstance(record, Mapping):
            errors.append("invalid_input_record")
        else:
            name = str(record.get("path", ""))
            target = (path.parent / name).resolve()
            if not target.is_file():
                errors.append(f"missing_input:{name}")
            elif _sha256(target) != record.get("sha256"):
                errors.append(f"input_hash_mismatch:{name}")
    records = manifest.get("outputs")
    if not isinstance(records, list):
        return {"valid": False, "errors": [*errors, "outputs_not_list"]}
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            errors.append("invalid_output_record")
            continue
        name = str(record.get("path", ""))
        target = path.parent / name
        if name in seen:
            errors.append(f"duplicate_output:{name}")
        seen.add(name)
        if not target.is_file():
            errors.append(f"missing_output:{name}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
    if seen != set(OUTPUT_NAMES):
        errors.append("output_set_mismatch")
    table = path.parent / "resources.csv"
    parsed_rows: list[dict[str, str]] = []
    if table.is_file():
        try:
            parsed_rows = list(csv.DictReader(table.open(encoding="utf-8")))
        except (OSError, csv.Error):
            errors.append("invalid_resources_csv")
    identities: set[tuple[str, str]] = set()
    for row in parsed_rows:
        track = str(row.get("track", ""))
        method = str(row.get("method_id", ""))
        if track not in RESOURCE_UNITS:
            errors.append(f"invalid_track:{track}")
            continue
        identity = (track, method)
        if identity in identities:
            errors.append(f"duplicate_method:{track}:{method}")
        identities.add(identity)
        status = row.get("status")
        if status not in {"auditable", "not_auditable"}:
            errors.append(f"invalid_status:{track}:{method}")
        try:
            usage = json.loads(row.get("mean_resources_json", ""))
        except json.JSONDecodeError:
            errors.append(f"invalid_resource_json:{track}:{method}")
            continue
        if status == "auditable":
            if set(usage) != set(RESOURCE_UNITS[track]):
                errors.append(f"invalid_resource_units:{track}:{method}")
            elif any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                for value in usage.values()
            ):
                errors.append(f"invalid_resource_value:{track}:{method}")
        elif usage:
            errors.append(f"not_auditable_has_resources:{track}:{method}")
    summary_path = path.parent / "summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append("invalid_summary")
        else:
            if summary.get("resource_units") != {
                key: list(value) for key, value in RESOURCE_UNITS.items()
            }:
                errors.append("summary_resource_units_mismatch")
            if summary.get("row_count") != len(parsed_rows):
                errors.append("summary_row_count_mismatch")
            observed_auditable = {
                track: sum(
                    row.get("track") == track and row.get("status") == "auditable"
                    for row in parsed_rows
                )
                for track in RESOURCE_UNITS
            }
            if summary.get("auditable_counts") != observed_auditable:
                errors.append("summary_auditable_counts_mismatch")
    return {"valid": not errors, "errors": errors, "row_count": len(parsed_rows)}


__all__ = [
    "MarketResourceReport",
    "MarketResourceRow",
    "RESOURCE_UNITS",
    "analyze_market_resources",
    "attach_resource_usage",
    "build_market_resource_report",
    "instrument_procurement_input",
    "trading_resource_usage",
    "verify_market_resource_report",
]
