"""Measure whether frozen benchmark cases distinguish flagship mechanisms."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import fmean, pvariance
from typing import Any, Iterable, Mapping

import yaml

from .metrics import MetricValue
from .metrology import PRIMARY_METRIC_RULES
from .models import BenchmarkResult
from .report import load_jsonl_results

EXACT_TOLERANCE = 1e-12
PRACTICAL_TOLERANCE: Mapping[str, float] = {
    "replication_owner_rank_change": 0.01,
    "oracle_ratio": 0.01,
    "gain_from_trade_ratio": 0.01,
}
METRIC_BOUNDS: Mapping[str, tuple[float, float]] = {
    "replication_owner_rank_change": (-1.0, 1.0),
    "oracle_ratio": (0.0, 1.0),
    "gain_from_trade_ratio": (0.0, 1.0),
}
OUTPUT_NAMES = ("track_discriminability.csv", "summary.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_value(row: BenchmarkResult, metric_id: str) -> Any:
    value = row.metrics.get(metric_id)
    if isinstance(value, MetricValue):
        return value.value if value.applicable else None
    return value


def _number(row: BenchmarkResult, metric_id: str) -> float | None:
    raw = _metric_value(row, metric_id)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _qualified(track: str, rows: Iterable[BenchmarkResult]) -> bool:
    records = tuple(rows)
    if not records:
        return False
    if track == "valuation":
        return True
    if track == "procurement":
        return all(
            _metric_value(row, "budget_violation") is False
            and _number(row, "seller_ir_violation_count") == 0.0
            for row in records
        )
    if track == "trading":
        return all(
            _metric_value(row, "individual_rationality") is True
            and _metric_value(row, "weak_budget_balance") is True
            for row in records
        )
    return False


def _winner_ids(scores: Mapping[str, float], direction: str) -> list[str]:
    if not scores:
        return []
    optimum = min(scores.values()) if direction == "lower" else max(scores.values())
    return sorted(
        method
        for method, value in scores.items()
        if math.isclose(value, optimum, rel_tol=EXACT_TOLERANCE, abs_tol=EXACT_TOLERANCE)
    )


def analyze_discriminability(
    results: Iterable[BenchmarkResult],
    *,
    headline_methods: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    """Aggregate seeds before measuring ties, saturation, and guardrail activity."""

    rows = tuple(results)
    tracks: dict[str, Any] = {}
    for track in sorted(headline_methods):
        methods = tuple(headline_methods[track])
        rule = PRIMARY_METRIC_RULES[track]
        metric_id = rule["metric_id"]
        selected = tuple(
            row
            for row in rows
            if row.track == track
            and row.method_id in methods
            and row.status == "completed"
            and row.metadata.get("primary_metric_eligible") is not False
        )
        global_blocks = sorted(
            {
                str(row.metadata.get("independent_block", "")).strip()
                for row in selected
                if str(row.metadata.get("independent_block", "")).strip()
            }
        )
        case_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        expected_case_keys: set[tuple[str, str, str]] = set()
        method_rows: dict[str, list[BenchmarkResult]] = defaultdict(list)
        for row in selected:
            block = str(row.metadata.get("independent_block", "")).strip()
            if not block:
                continue
            key = (row.method_id, block, row.case_id)
            expected_case_keys.add(key)
            method_rows[row.method_id].append(row)
            value = _number(row, metric_id)
            if value is not None:
                case_values[key].append(value)
        case_means = {
            key: fmean(values) for key, values in sorted(case_values.items()) if values
        }
        missing_measurements = len(expected_case_keys - set(case_means))
        block_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for (method, block, _case), value in case_means.items():
            block_values[method][block].append(value)
        block_means = {
            method: {
                block: fmean(values) for block, values in sorted(by_block.items())
            }
            for method, by_block in sorted(block_values.items())
        }
        scores = {
            method: fmean(values.values())
            for method, values in block_means.items()
            if values
        }
        complete = {
            method: score
            for method, score in scores.items()
            if set(block_means[method]) == set(global_blocks)
        }
        exact_ties = 0
        practical_ties = 0
        pairs = list(combinations(sorted(complete), 2))
        tolerance = PRACTICAL_TOLERANCE[metric_id]
        for left, right in pairs:
            difference = abs(complete[left] - complete[right])
            exact_ties += difference <= EXACT_TOLERANCE
            practical_ties += difference <= tolerance
        numeric_values = list(case_means.values())
        lower, upper = METRIC_BOUNDS[metric_id]
        ceiling = sum(abs(value - upper) <= tolerance for value in numeric_values)
        floor = sum(abs(value - lower) <= tolerance for value in numeric_values)
        qualified = {method: _qualified(track, method_rows.get(method, ())) for method in methods}
        active = {method: bool(method_rows.get(method)) and not qualified[method] for method in methods}
        method_scores = list(complete.values())
        within_variances = [
            pvariance(values.values())
            for values in block_means.values()
            if len(values) > 1
        ]
        denominator = len(numeric_values)
        tracks[track] = {
            "metric_id": metric_id,
            "direction": rule["direction"],
            "method_count": len(methods),
            "observed_method_count": len(scores),
            "complete_coverage_method_count": len(complete),
            "block_count": len(global_blocks),
            "missing_measurement_count": missing_measurements,
            "pair_count": len(pairs),
            "exact_tie_pair_count": exact_ties,
            "exact_tie_rate": exact_ties / len(pairs) if pairs else None,
            "practical_tie_pair_count": practical_ties,
            "practical_tie_rate": practical_ties / len(pairs) if pairs else None,
            "practical_tolerance": tolerance,
            "winner_ids": _winner_ids(complete, rule["direction"]),
            "winner_set_size": len(_winner_ids(complete, rule["direction"])),
            "between_method_variance": pvariance(method_scores) if len(method_scores) > 1 else 0.0,
            "mean_within_method_block_variance": fmean(within_variances) if within_variances else 0.0,
            "ceiling_saturation_rate": ceiling / denominator if denominator else None,
            "floor_saturation_rate": floor / denominator if denominator else None,
            "qualification_rate": sum(qualified.values()) / len(methods) if methods else None,
            "constraint_activation_rate": sum(active.values()) / len(methods) if methods else None,
            "qualified_method_ids": sorted(method for method, value in qualified.items() if value),
        }
    return {
        "valid": set(tracks) == set(headline_methods),
        "tracks": tracks,
    }


def build_discriminability_audit(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    catalog_path: str | Path,
    waves: Mapping[str, str | Path],
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)

    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    catalog = yaml.safe_load(resolve(catalog_path).read_text(encoding="utf-8")) or {}
    headline = {
        track: tuple(item["method_ids"])
        for track, item in catalog["flagships"].items()
    }
    wave_reports = {
        wave: analyze_discriminability(
            load_jsonl_results(resolve(path)), headline_methods=headline
        )
        for wave, path in sorted(waves.items())
    }
    valid = bool(wave_reports) and all(report["valid"] for report in wave_reports.values())
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-discriminability-v1",
        "valid": valid,
        "waves": wave_reports,
        "claim_boundary": (
            "Discriminability is descriptive over frozen method sets and cases; "
            "fixed tolerances are not tuned to obtain pairwise separation."
        ),
    }
    with (output / "track_discriminability.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        columns = ("wave", "track", *next(iter(next(iter(wave_reports.values()))["tracks"].values())).keys())
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for wave, report in wave_reports.items():
            for track, record in report["tracks"].items():
                writer.writerow(
                    {
                        "wave": wave,
                        "track": track,
                        **{
                            key: ";".join(value) if isinstance(value, list) else value
                            for key, value in record.items()
                        },
                    }
                )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inputs = [resolve(catalog_path), *(resolve(path) for path in waves.values())]
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "discriminability_audit",
        "inputs": [{"path": str(path), "sha256": _sha256(path)} for path in inputs],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_discriminability_audit(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    seen: set[str] = set()
    for record in payload.get("outputs", []):
        name = str(record.get("path", ""))
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_output:{name}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
    if seen != set(OUTPUT_NAMES):
        errors.append("output_set_mismatch")
    summary = path.parent / "summary.json"
    if summary.is_file() and not json.loads(summary.read_text(encoding="utf-8")).get("valid"):
        errors.append("invalid_summary")
    return {"valid": not errors, "errors": errors}


__all__ = [
    "analyze_discriminability",
    "build_discriminability_audit",
    "verify_discriminability_audit",
]

