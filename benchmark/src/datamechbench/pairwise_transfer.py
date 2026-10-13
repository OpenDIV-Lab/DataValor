"""Prospective pairwise ordering transfer across frozen benchmark waves."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

import yaml

from .discriminability import PRACTICAL_TOLERANCE
from .metrics import MetricValue
from .metrology import PRIMARY_METRIC_RULES
from .models import BenchmarkResult
from .report import load_jsonl_results

RELATIONS = ("left_better", "practical_tie", "right_better")
TRANSFER_CATEGORIES = (
    "stable_order",
    "stable_tie",
    "attenuation_to_tie",
    "emerging_order",
    "reversal",
)
OUTPUT_NAMES = ("pairwise_transfer.csv", "summary.json", "report.md")


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


def classify_relation(advantage: float, tolerance: float) -> str:
    """Classify an oriented advantage using a fixed practical tolerance."""

    if not math.isfinite(advantage):
        raise ValueError("advantage must be finite")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    if abs(advantage) <= tolerance:
        return "practical_tie"
    return "left_better" if advantage > 0 else "right_better"


def classify_transfer(v1_relation: str, v2_relation: str) -> str:
    """Map two wave relations to one exhaustive transfer category."""

    if v1_relation not in RELATIONS or v2_relation not in RELATIONS:
        raise ValueError("unsupported pairwise relation")
    if v1_relation == "practical_tie" and v2_relation == "practical_tie":
        return "stable_tie"
    if v1_relation == "practical_tie":
        return "emerging_order"
    if v2_relation == "practical_tie":
        return "attenuation_to_tie"
    if v1_relation == v2_relation:
        return "stable_order"
    return "reversal"


def _aggregate_wave(
    rows: Iterable[BenchmarkResult],
    *,
    wave: str,
    track: str,
    methods: tuple[str, ...],
    metric_id: str,
) -> tuple[dict[str, float], int, list[str]]:
    selected = tuple(
        row
        for row in rows
        if row.track == track
        and row.method_id in methods
        and row.status == "completed"
        and row.metadata.get("primary_metric_eligible") is not False
    )
    errors: list[str] = []
    seen_runs: set[tuple[str, str, str, int]] = set()
    block_cases: dict[str, set[str]] = defaultdict(set)
    case_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    observed_methods: set[str] = set()
    for row in selected:
        block = str(row.metadata.get("independent_block", "")).strip()
        if not block:
            errors.append(f"missing_block:{wave}:{track}:{row.run_id}")
            continue
        run_key = (row.method_id, block, row.case_id, row.seed)
        if run_key in seen_runs:
            errors.append(
                f"duplicate_measurement:{wave}:{track}:{row.method_id}:{block}:{row.case_id}:{row.seed}"
            )
            continue
        seen_runs.add(run_key)
        observed_methods.add(row.method_id)
        block_cases[block].add(row.case_id)
        value = _number(row, metric_id)
        if value is None:
            errors.append(
                f"missing_measurement:{wave}:{track}:{row.method_id}:{block}:{row.case_id}:{row.seed}"
            )
            continue
        case_values[(row.method_id, block, row.case_id)].append(value)

    for method in methods:
        if method not in observed_methods:
            errors.append(f"missing_method_wave:{wave}:{track}:{method}")

    case_means = {
        key: fmean(values) for key, values in sorted(case_values.items()) if values
    }
    block_means: dict[str, dict[str, float]] = defaultdict(dict)
    for method in methods:
        for block, cases in sorted(block_cases.items()):
            missing = sorted(
                case for case in cases if (method, block, case) not in case_means
            )
            if missing:
                errors.append(
                    f"incomplete_case_coverage:{wave}:{track}:{method}:{block}:"
                    + ",".join(missing)
                )
                continue
            block_means[method][block] = fmean(
                case_means[(method, block, case)] for case in sorted(cases)
            )

    expected_blocks = set(block_cases)
    scores = {
        method: fmean(by_block.values())
        for method, by_block in sorted(block_means.items())
        if set(by_block) == expected_blocks and expected_blocks
    }
    return scores, len(expected_blocks), sorted(set(errors))


def analyze_pairwise_transfer(
    v1_results: Iterable[BenchmarkResult],
    v2_results: Iterable[BenchmarkResult],
    *,
    headline_methods: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    """Compare every headline method pair without pooling frozen waves."""

    waves = {"v1": tuple(v1_results), "v2": tuple(v2_results)}
    errors: list[str] = []
    pairs: list[dict[str, Any]] = []
    tracks: dict[str, Any] = {}
    for track in sorted(headline_methods):
        methods = tuple(sorted(headline_methods[track]))
        if len(methods) != len(set(methods)):
            errors.append(f"duplicate_method_id:{track}")
        rule = PRIMARY_METRIC_RULES[track]
        metric_id = str(rule["metric_id"])
        direction = str(rule["direction"])
        tolerance = PRACTICAL_TOLERANCE[metric_id]
        scores: dict[str, dict[str, float]] = {}
        block_counts: dict[str, int] = {}
        for wave, rows in waves.items():
            wave_scores, block_count, wave_errors = _aggregate_wave(
                rows,
                wave=wave,
                track=track,
                methods=methods,
                metric_id=metric_id,
            )
            scores[wave] = wave_scores
            block_counts[wave] = block_count
            errors.extend(wave_errors)

        track_pairs: list[dict[str, Any]] = []
        for left, right in combinations(methods, 2):
            if any(left not in scores[wave] or right not in scores[wave] for wave in waves):
                continue
            advantages = {
                wave: (
                    scores[wave][left] - scores[wave][right]
                    if direction == "higher"
                    else scores[wave][right] - scores[wave][left]
                )
                for wave in waves
            }
            relations = {
                wave: classify_relation(advantage, tolerance)
                for wave, advantage in advantages.items()
            }
            record = {
                "track": track,
                "metric_id": metric_id,
                "direction": direction,
                "left_method_id": left,
                "right_method_id": right,
                "practical_tolerance": tolerance,
                "v1_left_score": scores["v1"][left],
                "v1_right_score": scores["v1"][right],
                "v1_left_advantage": advantages["v1"],
                "v1_relation": relations["v1"],
                "v2_left_score": scores["v2"][left],
                "v2_right_score": scores["v2"][right],
                "v2_left_advantage": advantages["v2"],
                "v2_relation": relations["v2"],
                "transfer_category": classify_transfer(
                    relations["v1"], relations["v2"]
                ),
            }
            track_pairs.append(record)
            pairs.append(record)

        expected_pair_count = len(methods) * (len(methods) - 1) // 2
        observed_pair_count = len(track_pairs)
        if observed_pair_count != expected_pair_count:
            errors.append(
                f"incomplete_pair_coverage:{track}:{observed_pair_count}/{expected_pair_count}"
            )
        category_counts = {
            category: sum(
                pair["transfer_category"] == category for pair in track_pairs
            )
            for category in TRANSFER_CATEGORIES
        }
        v1_ties = sum(pair["v1_relation"] == "practical_tie" for pair in track_pairs)
        v2_ties = sum(pair["v2_relation"] == "practical_tie" for pair in track_pairs)
        v1_separable = observed_pair_count - v1_ties
        v2_separable = observed_pair_count - v2_ties
        ordered_both = category_counts["stable_order"] + category_counts["reversal"]
        tracks[track] = {
            "method_count": len(methods),
            "expected_pair_count": expected_pair_count,
            "observed_pair_count": observed_pair_count,
            "metric_id": metric_id,
            "direction": direction,
            "practical_tolerance": tolerance,
            "block_counts": block_counts,
            "category_counts": category_counts,
            "v1_separable_pair_count": v1_separable,
            "v2_separable_pair_count": v2_separable,
            "v1_practical_tie_rate": v1_ties / observed_pair_count if observed_pair_count else None,
            "v2_practical_tie_rate": v2_ties / observed_pair_count if observed_pair_count else None,
            "separation_retention_rate": (
                category_counts["stable_order"] / v1_separable
                if v1_separable
                else None
            ),
            "reversal_rate_among_ordered_both": (
                category_counts["reversal"] / ordered_both if ordered_both else None
            ),
        }

    unique_errors = sorted(set(errors))
    return {
        "valid": not unique_errors,
        "errors": unique_errors,
        "pair_count": len(pairs),
        "tracks": tracks,
        "pairs": sorted(
            pairs,
            key=lambda row: (
                row["track"], row["left_method_id"], row["right_method_id"]
            ),
        ),
    }


def _report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Pairwise ordering transfer",
        "",
        "Every headline method pair is classified prospectively from v1 to the separately frozen v2 wave.",
        "",
        "| Track | Pairs | Stable order | Stable tie | To tie | Emerging | Reversal |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for track, record in summary["tracks"].items():
        counts = record["category_counts"]
        lines.append(
            f"| {track} | {record['observed_pair_count']} | "
            f"{counts['stable_order']} | {counts['stable_tie']} | "
            f"{counts['attenuation_to_tie']} | {counts['emerging_order']} | "
            f"{counts['reversal']} |"
        )
    lines.extend(
        [
            "",
            "Relations use fixed practical tolerances and equal block weighting. They are descriptive resolution diagnostics, not significance tests or population rankings.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_pairwise_transfer_audit(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    catalog_path: str | Path,
    v1_path: str | Path,
    v2_path: str | Path,
) -> dict[str, Any]:
    """Build deterministic pairwise transfer artifacts from frozen waves."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)

    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    catalog_file = resolve(catalog_path)
    v1_file = resolve(v1_path)
    v2_file = resolve(v2_path)
    catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8")) or {}
    headline = {
        track: tuple(record["method_ids"])
        for track, record in catalog["flagships"].items()
    }
    analysis = analyze_pairwise_transfer(
        load_jsonl_results(v1_file),
        load_jsonl_results(v2_file),
        headline_methods=headline,
    )
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-pairwise-order-transfer-v1",
        **analysis,
        "claim_boundary": (
            "Pair relations are descriptive at fixed practical tolerances; waves are not pooled, "
            "and stable ordering does not establish population or cross-source superiority."
        ),
    }
    csv_path = output / "pairwise_transfer.csv"
    columns = tuple(summary["pairs"][0]) if summary["pairs"] else (
        "track",
        "left_method_id",
        "right_method_id",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary["pairs"])
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        _report_markdown(summary), encoding="utf-8"
    )
    inputs = (catalog_file, v1_file, v2_file)
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "pairwise_transfer_audit",
        "inputs": [
            {"path": str(path), "sha256": _sha256(path)} for path in inputs
        ],
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


def verify_pairwise_transfer_audit(manifest_path: str | Path) -> dict[str, Any]:
    """Verify output coverage and hashes for a pairwise transfer artifact."""

    path = Path(manifest_path)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if payload.get("manifest_kind") != "pairwise_transfer_audit":
        errors.append("invalid_manifest_kind")
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
    summary_path = path.parent / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not summary.get("valid") or summary.get("pair_count") != 40:
            errors.append("invalid_summary")
        expected_pairs = {"valuation": 15, "procurement": 15, "trading": 10}
        tracks = summary.get("tracks", {})
        pair_rows = summary.get("pairs", [])
        if not isinstance(tracks, dict) or set(tracks) != set(expected_pairs):
            errors.append("invalid_track_set")
            tracks = {}
        if not isinstance(pair_rows, list) or len(pair_rows) != 40:
            errors.append("invalid_pair_rows")
            pair_rows = []
        pair_keys: set[tuple[str, str, str]] = set()
        observed_categories: dict[str, dict[str, int]] = {
            track: {category: 0 for category in TRANSFER_CATEGORIES}
            for track in expected_pairs
        }
        for record in pair_rows:
            if not isinstance(record, dict):
                errors.append("invalid_pair_record")
                continue
            track = str(record.get("track", ""))
            left = str(record.get("left_method_id", ""))
            right = str(record.get("right_method_id", ""))
            category = str(record.get("transfer_category", ""))
            key = (track, left, right)
            if (
                track not in expected_pairs
                or not left
                or not right
                or left >= right
                or category not in TRANSFER_CATEGORIES
                or key in pair_keys
            ):
                errors.append("invalid_pair_record")
                continue
            pair_keys.add(key)
            observed_categories[track][category] += 1
        for track, expected in expected_pairs.items():
            record = tracks.get(track, {})
            categories = record.get("category_counts", {}) if isinstance(record, dict) else {}
            valid_counts = (
                isinstance(categories, dict)
                and set(categories) == set(TRANSFER_CATEGORIES)
                and all(
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    for value in categories.values()
                )
            )
            if (
                not valid_counts
                or sum(categories.values()) != expected
                or categories != observed_categories[track]
                or record.get("expected_pair_count") != expected
                or record.get("observed_pair_count") != expected
            ):
                errors.append(f"invalid_category_partition:{track}")
    return {"valid": not errors, "errors": sorted(set(errors))}


__all__ = [
    "analyze_pairwise_transfer",
    "build_pairwise_transfer_audit",
    "classify_relation",
    "classify_transfer",
    "verify_pairwise_transfer_audit",
]
