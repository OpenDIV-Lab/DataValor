"""Quality--query frontiers with explicit auditability boundaries."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .metrics import MetricValue
from .models import BenchmarkResult, ValuationOutput
from .outcomes import parse_outcome
from .report import load_jsonl_results

OUTPUT_NAMES = ("frontier.csv", "track_status.csv", "summary.json")


@dataclass(frozen=True)
class ResourceFrontierRow:
    method_id: str
    status: str
    quality_metric_id: str
    mean_quality: float | None
    mean_query_calls: float | None
    block_count: int
    run_count: int
    nondominated: bool | None
    dominated_by: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class ResourceFrontierReport:
    methods: tuple[ResourceFrontierRow, ...]
    track_status: Mapping[str, str]


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


def analyze_resource_frontier(
    results: Iterable[BenchmarkResult],
    *,
    quality_metric_id: str = "topk_test_utility",
) -> ResourceFrontierReport:
    """Aggregate source blocks equally and compute the valuation Pareto set."""

    rows = tuple(
        row
        for row in results
        if row.track == "valuation" and row.status == "completed"
    )
    methods: list[ResourceFrontierRow] = []
    for method_id in sorted({row.method_id for row in rows}):
        method_rows = tuple(row for row in rows if row.method_id == method_id)
        measurements: list[tuple[str, float, int]] = []
        reason: str | None = None
        for row in method_rows:
            quality = _metric_number(row, quality_metric_id)
            if quality is None:
                reason = "missing_quality_metric"
                break
            try:
                outcome = parse_outcome(row.track, row.outcome or {})
            except ValueError:
                reason = "invalid_outcome"
                break
            if not isinstance(outcome, ValuationOutput):
                reason = "invalid_outcome"
                break
            if outcome.utility_calls is None:
                reason = "missing_utility_calls"
                break
            block = str(row.metadata.get("independent_block", "")).strip()
            if not block:
                reason = "missing_independent_block"
                break
            measurements.append((block, quality, outcome.utility_calls))
        if reason is not None:
            methods.append(
                ResourceFrontierRow(
                    method_id=method_id,
                    status="not_auditable",
                    quality_metric_id=quality_metric_id,
                    mean_quality=None,
                    mean_query_calls=None,
                    block_count=0,
                    run_count=len(method_rows),
                    nondominated=None,
                    dominated_by=(),
                    reason=reason,
                )
            )
            continue
        blocks = sorted({block for block, _, _ in measurements})
        block_quality = [
            fmean(value for block_id, value, _ in measurements if block_id == block)
            for block in blocks
        ]
        block_calls = [
            fmean(value for block_id, _, value in measurements if block_id == block)
            for block in blocks
        ]
        methods.append(
            ResourceFrontierRow(
                method_id=method_id,
                status="auditable",
                quality_metric_id=quality_metric_id,
                mean_quality=fmean(block_quality),
                mean_query_calls=fmean(block_calls),
                block_count=len(blocks),
                run_count=len(method_rows),
                nondominated=False,
                dominated_by=(),
            )
        )

    auditable = tuple(row for row in methods if row.status == "auditable")
    rewritten: list[ResourceFrontierRow] = []
    for row in methods:
        if row.status != "auditable":
            rewritten.append(row)
            continue
        assert row.mean_quality is not None and row.mean_query_calls is not None
        dominators = tuple(
            other.method_id
            for other in auditable
            if other.method_id != row.method_id
            and other.mean_quality is not None
            and other.mean_query_calls is not None
            and other.mean_quality >= row.mean_quality
            and other.mean_query_calls <= row.mean_query_calls
            and (
                other.mean_quality > row.mean_quality
                or other.mean_query_calls < row.mean_query_calls
            )
        )
        rewritten.append(
            ResourceFrontierRow(
                **{
                    **vars(row),
                    "nondominated": not dominators,
                    "dominated_by": tuple(sorted(dominators)),
                }
            )
        )
    return ResourceFrontierReport(
        tuple(rewritten),
        {
            "valuation": "auditable" if auditable else "not_auditable:no_complete_method",
            "procurement": "not_auditable:no_standardized_query_counter",
            "trading": "not_auditable:no_standardized_query_counter",
        },
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_resource_frontier(
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
    report = analyze_resource_frontier(load_jsonl_results(source))
    with (output / "frontier.csv").open("w", encoding="utf-8", newline="") as stream:
        columns = (
            "method_id",
            "status",
            "quality_metric_id",
            "mean_quality",
            "mean_query_calls",
            "block_count",
            "run_count",
            "nondominated",
            "dominated_by",
            "reason",
        )
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in report.methods:
            writer.writerow({**vars(row), "dominated_by": ";".join(row.dominated_by)})
    with (output / "track_status.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("track", "status"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {"track": track, "status": status}
            for track, status in sorted(report.track_status.items())
        )
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-resource-frontier-v1",
        "valid": bool(report.methods),
        "quality_metric_id": "topk_test_utility",
        "query_metric_id": "utility_calls",
        "auditable_method_count": sum(row.status == "auditable" for row in report.methods),
        "nondominated_method_ids": [
            row.method_id for row in report.methods if row.nondominated is True
        ],
        "track_status": dict(report.track_status),
        "claim_boundary": (
            "The frontier is descriptive over the frozen held-out valuation blocks; "
            "procurement and trading use their separate track-native resource-vector "
            "audit rather than being forced onto valuation utility-call units."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "resource_frontier",
        "inputs": [{"path": str(results_path), "sha256": _sha256(source)}],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_resource_frontier(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    errors: list[str] = []
    outputs = payload.get("outputs", [])
    seen: set[str] = set()
    for record in outputs if isinstance(outputs, list) else ():
        name = str(record.get("path", "")) if isinstance(record, Mapping) else ""
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_or_invalid:{name}")
        elif _sha256(target) != str(record.get("sha256", "")):
            errors.append(f"hash_mismatch:{name}")
    errors.extend(f"missing_binding:{name}" for name in sorted(set(OUTPUT_NAMES) - seen))
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "ResourceFrontierReport",
    "ResourceFrontierRow",
    "analyze_resource_frontier",
    "build_resource_frontier",
    "verify_resource_frontier",
]
