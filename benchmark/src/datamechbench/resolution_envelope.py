"""Fixed-grid resolution sensitivity for frozen headline comparisons."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

import yaml

from .metrics import MetricValue
from .metrology import PRIMARY_METRIC_RULES
from .models import BenchmarkResult
from .pairwise_transfer import _aggregate_wave
from .report import load_jsonl_results

OUTPUT_NAMES = ("pair_tolerance_envelope.csv", "summary.json", "report.md")


def _tolerance_key(value: float) -> str:
    return format(value, ".15g")


def _number(row: BenchmarkResult, metric_id: str) -> float | None:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        raw = raw.value if raw.applicable else None
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _challenge_differences(
    rows: Iterable[BenchmarkResult],
    *,
    track: str,
    methods: tuple[str, ...],
    metric_id: str,
) -> tuple[dict[tuple[str, str], float], int, list[str]]:
    selected = tuple(
        row
        for row in rows
        if row.track == track
        and row.method_id in methods
        and row.status == "completed"
        and row.metadata.get("primary_metric_eligible") is not False
    )
    errors: list[str] = []
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    for row in selected:
        key = (row.method_id, row.case_id, row.seed)
        if key in seen:
            errors.append(
                f"duplicate_challenge_measurement:{track}:{row.method_id}:{row.case_id}:{row.seed}"
            )
            continue
        seen.add(key)
        value = _number(row, metric_id)
        if value is None:
            errors.append(
                f"missing_challenge_measurement:{track}:{row.method_id}:{row.case_id}:{row.seed}"
            )
            continue
        values[(row.method_id, row.case_id)].append(value)
    case_ids = sorted({case for _, case in values})
    for method in methods:
        missing = [case for case in case_ids if (method, case) not in values]
        if missing:
            errors.append(
                f"incomplete_challenge_coverage:{track}:{method}:" + ",".join(missing)
            )
    means = {key: fmean(items) for key, items in values.items() if items}
    differences: dict[tuple[str, str], float] = {}
    for left, right in itertools.combinations(sorted(methods), 2):
        if all((left, case) in means and (right, case) in means for case in case_ids):
            differences[(left, right)] = max(
                abs(means[(left, case)] - means[(right, case)]) for case in case_ids
            )
    return differences, len(case_ids), sorted(set(errors))


def analyze_resolution_envelope(
    v1_results: Iterable[BenchmarkResult],
    v2_results: Iterable[BenchmarkResult],
    challenge_results: Iterable[BenchmarkResult],
    *,
    headline_methods: Mapping[str, tuple[str, ...]],
    tolerances: tuple[float, ...],
) -> dict[str, Any]:
    """Measure complete headline-pair separation across a fixed tolerance grid."""

    if (
        not tolerances
        or tuple(sorted(set(tolerances))) != tolerances
        or any(not math.isfinite(value) or value < 0 for value in tolerances)
    ):
        raise ValueError("tolerances must be unique, sorted, finite, and non-negative")
    waves = {
        "heldout_v1": tuple(v1_results),
        "heldout_v2": tuple(v2_results),
    }
    challenge = tuple(challenge_results)
    errors: list[str] = []
    pair_rows: list[dict[str, Any]] = []
    panels: dict[str, dict[str, Any]] = {
        "heldout_v1": {},
        "heldout_v2": {},
        "challenge": {},
    }

    def add_panel(
        panel: str,
        track: str,
        methods: tuple[str, ...],
        metric_id: str,
        differences: Mapping[tuple[str, str], float],
        unit_count: int,
    ) -> None:
        expected = len(methods) * (len(methods) - 1) // 2
        if len(differences) != expected:
            errors.append(
                f"incomplete_pair_coverage:{panel}:{track}:{len(differences)}/{expected}"
            )
        counts: dict[str, int] = {}
        for tolerance in tolerances:
            key = _tolerance_key(tolerance)
            counts[key] = sum(value > tolerance for value in differences.values())
            for (left, right), value in sorted(differences.items()):
                pair_rows.append(
                    {
                        "panel": panel,
                        "track": track,
                        "metric_id": metric_id,
                        "left_method_id": left,
                        "right_method_id": right,
                        "tolerance": tolerance,
                        "max_or_aggregate_absolute_difference": value,
                        "separable": value > tolerance,
                    }
                )
        monotone = all(
            counts[_tolerance_key(left)] >= counts[_tolerance_key(right)]
            for left, right in zip(tolerances, tolerances[1:])
        )
        if not monotone:
            errors.append(f"nonmonotone_separation:{panel}:{track}")
        panels[panel][track] = {
            "method_count": len(methods),
            "pair_count": expected,
            "independent_unit_count": unit_count,
            "separable_pair_counts": counts,
            "robustly_separable_pair_count": counts[_tolerance_key(tolerances[-1])],
            "ever_separable_pair_count": counts[_tolerance_key(tolerances[0])],
            "monotonicity_passed": monotone,
        }

    for track, configured in sorted(headline_methods.items()):
        methods = tuple(sorted(configured))
        if len(methods) != len(set(methods)):
            errors.append(f"duplicate_method:{track}")
            continue
        rule = PRIMARY_METRIC_RULES[track]
        metric_id = str(rule["metric_id"])
        for panel, rows in waves.items():
            scores, unit_count, wave_errors = _aggregate_wave(
                rows,
                wave=panel,
                track=track,
                methods=methods,
                metric_id=metric_id,
            )
            errors.extend(wave_errors)
            differences = {
                (left, right): abs(scores[left] - scores[right])
                for left, right in itertools.combinations(methods, 2)
                if left in scores and right in scores
            }
            add_panel(panel, track, methods, metric_id, differences, unit_count)
        challenge_tracks = {row.track for row in challenge}
        if track in challenge_tracks:
            differences, case_count, challenge_errors = _challenge_differences(
                challenge,
                track=track,
                methods=methods,
                metric_id=metric_id,
            )
            errors.extend(challenge_errors)
            add_panel(
                "challenge", track, methods, metric_id, differences, case_count
            )

    monotonicity = all(
        record["monotonicity_passed"]
        for tracks in panels.values()
        for record in tracks.values()
    )
    unique_errors = sorted(set(errors))
    return {
        "valid": not unique_errors,
        "errors": unique_errors,
        "tolerances": list(tolerances),
        "panels": panels,
        "monotonicity_passed": monotonicity,
        "pair_tolerance_row_count": len(pair_rows),
        "pair_tolerance_rows": sorted(
            pair_rows,
            key=lambda row: (
                row["panel"],
                row["track"],
                row["left_method_id"],
                row["right_method_id"],
                row["tolerance"],
            ),
        ),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(summary: Mapping[str, Any], primary_tolerance: float) -> str:
    lines = [
        "# Resolution sensitivity envelope",
        "",
        "Pair separation is reported for every fixed tolerance; 0.01 remains the primary convention and the other cells are sensitivity analyses.",
        "",
        "| Panel | Track | Pairs | "
        + " | ".join(f"sep @ {_tolerance_key(value)}" for value in summary["tolerances"])
        + " | robust at max |",
        "|---|---|---:|" + "---:|" * (len(summary["tolerances"]) + 1),
    ]
    for panel, tracks in summary["panels"].items():
        for track, record in tracks.items():
            counts = record["separable_pair_counts"]
            lines.append(
                f"| {panel} | {track} | {record['pair_count']} | "
                + " | ".join(str(counts[_tolerance_key(value)]) for value in summary["tolerances"])
                + f" | {record['robustly_separable_pair_count']} |"
            )
    lines.extend(
        [
            "",
            f"Primary tolerance: `{_tolerance_key(primary_tolerance)}`.",
            "",
            "The envelope is descriptive. It neither changes the frozen leaderboard tolerance nor establishes statistical or population superiority.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_protocol(path: Path) -> tuple[tuple[float, ...], float, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported resolution protocol")
    tolerances = tuple(float(value) for value in raw.get("tolerances", ()))
    primary = float(raw.get("primary_tolerance"))
    if primary not in tolerances:
        raise ValueError("primary tolerance must be present in the grid")
    return tolerances, primary, str(raw.get("study_id", ""))


def build_resolution_envelope(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    catalog_path: str | Path,
    protocol_path: str | Path,
    v1_path: str | Path,
    v2_path: str | Path,
    challenge_path: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    def resolve(value: str | Path) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else root / candidate

    catalog_file = resolve(catalog_path)
    protocol_file = resolve(protocol_path)
    v1_file = resolve(v1_path)
    v2_file = resolve(v2_path)
    challenge_file = resolve(challenge_path)
    catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8")) or {}
    headline = {
        track: tuple(record["method_ids"])
        for track, record in catalog["flagships"].items()
    }
    tolerances, primary, study_id = _load_protocol(protocol_file)
    analysis = analyze_resolution_envelope(
        load_jsonl_results(v1_file),
        load_jsonl_results(v2_file),
        load_jsonl_results(challenge_file),
        headline_methods=headline,
        tolerances=tolerances,
    )
    pair_rows = analysis["pair_tolerance_rows"]
    analysis_summary = {
        key: value
        for key, value in analysis.items()
        if key != "pair_tolerance_rows"
    }
    summary = {
        "schema_version": "1.0",
        "study_id": study_id,
        "primary_tolerance": primary,
        **analysis_summary,
        "claim_boundary": (
            "Post-freeze descriptive sensitivity analysis; it does not redefine the "
            "primary tolerance or establish population rankings."
        ),
    }
    csv_path = output / OUTPUT_NAMES[0]
    columns = (
        "panel",
        "track",
        "metric_id",
        "left_method_id",
        "right_method_id",
        "tolerance",
        "max_or_aggregate_absolute_difference",
        "separable",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(pair_rows)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(_report(summary, primary), encoding="utf-8")
    inputs = {
        "catalog": catalog_file,
        "protocol": protocol_file,
        "v1": v1_file,
        "v2": v2_file,
        "challenge": challenge_file,
    }
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "resolution_sensitivity_envelope",
        "inputs": {
            key: {
                "path": os.path.relpath(path, output),
                "sha256": _sha256(path),
            }
            for key, path in inputs.items()
        },
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)}
            for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def verify_resolution_envelope(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if manifest.get("schema_version") != "1.0" or manifest.get("manifest_kind") != "resolution_sensitivity_envelope":
        errors.append("invalid_manifest_contract")
    inputs: dict[str, Path] = {}
    for key in ("catalog", "protocol", "v1", "v2", "challenge"):
        record = manifest.get("inputs", {}).get(key, {})
        source = path.parent / str(record.get("path", ""))
        inputs[key] = source
        if not source.is_file():
            errors.append(f"missing_input:{key}")
        elif _sha256(source) != record.get("sha256"):
            errors.append(f"input_hash_mismatch:{key}")
    seen: set[str] = set()
    for record in manifest.get("outputs", []):
        name = str(record.get("path", ""))
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_output:{name}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"output_hash_mismatch:{name}")
    if seen != set(OUTPUT_NAMES):
        errors.append("output_set_mismatch")
    if not errors:
        try:
            catalog = yaml.safe_load(inputs["catalog"].read_text(encoding="utf-8")) or {}
            headline = {
                track: tuple(record["method_ids"])
                for track, record in catalog["flagships"].items()
            }
            tolerances, primary, study_id = _load_protocol(inputs["protocol"])
            recomputed = analyze_resolution_envelope(
                load_jsonl_results(inputs["v1"]),
                load_jsonl_results(inputs["v2"]),
                load_jsonl_results(inputs["challenge"]),
                headline_methods=headline,
                tolerances=tolerances,
            )
            recomputed_summary = {
                key: value
                for key, value in recomputed.items()
                if key != "pair_tolerance_rows"
            }
            observed = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
            expected = {
                "schema_version": "1.0",
                "study_id": study_id,
                "primary_tolerance": primary,
                **recomputed_summary,
                "claim_boundary": (
                    "Post-freeze descriptive sensitivity analysis; it does not redefine the "
                    "primary tolerance or establish population rankings."
                ),
            }
            if observed != expected:
                errors.append("semantic_recomputation_mismatch")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"semantic_recomputation_failed:{exc}")
    return {"valid": not errors, "errors": sorted(set(errors))}


__all__ = [
    "analyze_resolution_envelope",
    "build_resolution_envelope",
    "verify_resolution_envelope",
]
