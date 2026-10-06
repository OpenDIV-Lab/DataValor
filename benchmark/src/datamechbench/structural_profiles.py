"""Block-aware response curves for the three flagship mechanism settings."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping

import numpy as np

from .leaderboard import canonical_case_values
from .models import BenchmarkResult


@dataclass(frozen=True)
class StructuralAxisSpec:
    setting: str
    axis_field: str
    axis_name: str
    block_field: str
    block_name: str


STRUCTURAL_AXIS_SPECS = {
    "V-REPLICATION-ROBUSTNESS": StructuralAxisSpec(
        "V-REPLICATION-ROBUSTNESS",
        "replication_factor",
        "replication_factor",
        "replication_group_id",
        "dataset_owner",
    ),
    "P-MARKET-CONCENTRATION": StructuralAxisSpec(
        "P-MARKET-CONCENTRATION",
        "largest_singleton_share",
        "largest_singleton_share",
        "budget_item_count",
        "budget_item_count",
    ),
    "T-MARKET-THICKNESS": StructuralAxisSpec(
        "T-MARKET-THICKNESS",
        "efficient_trade_count",
        "efficient_trade_count",
        "surplus_margin_profile",
        "surplus_margin_profile",
    ),
}


@dataclass(frozen=True)
class StructuralCurvePoint:
    track: str
    setting: str
    family_id: str
    method_id: str
    primary_metric: str
    direction: str
    axis_name: str
    block_name: str
    block_id: str
    case_id: str
    axis_value: float
    normalized_axis: float
    primary_value: float
    oriented_value: float
    observation_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StructuralProfile:
    track: str
    setting: str
    family_id: str
    method_id: str
    primary_metric: str
    direction: str
    axis_name: str
    block_name: str
    case_count: int
    observation_count: int
    block_count: int
    expected_block_count: int
    coverage_ratio: float
    mean_primary: float
    worst_case_primary: float
    oriented_axis_auc: float
    oriented_slope: float
    oriented_endpoint_change: float
    nondegradation_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _case_metadata(
    results: tuple[BenchmarkResult, ...], spec: StructuralAxisSpec
) -> dict[str, Mapping[str, object]]:
    metadata: dict[str, Mapping[str, object]] = {}
    for result in results:
        if result.metadata.get("benchmark_setting") != spec.setting:
            continue
        if not result.metadata.get("primary_metric_eligible", True):
            continue
        if spec.axis_field not in result.metadata or spec.block_field not in result.metadata:
            continue
        previous = metadata.get(result.case_id)
        if previous is not None and (
            previous[spec.axis_field] != result.metadata[spec.axis_field]
            or previous[spec.block_field] != result.metadata[spec.block_field]
        ):
            raise ValueError(
                f"conflicting structural metadata for {spec.setting}/{result.case_id}"
            )
        metadata.setdefault(result.case_id, result.metadata)
    return metadata


def structural_curve_points(
    results: Iterable[BenchmarkResult],
) -> tuple[StructuralCurvePoint, ...]:
    """Return seed-averaged family curves with the axis normalized inside each block."""

    materialized = tuple(results)
    points: list[StructuralCurvePoint] = []
    for setting, spec in STRUCTURAL_AXIS_SPECS.items():
        metadata = _case_metadata(materialized, spec)
        if not metadata:
            continue
        block_ranges: dict[str, tuple[float, float]] = {}
        for case_metadata in metadata.values():
            block_id = str(case_metadata[spec.block_field])
            axis_value = float(case_metadata[spec.axis_field])
            if block_id not in block_ranges:
                block_ranges[block_id] = (axis_value, axis_value)
            else:
                lower, upper = block_ranges[block_id]
                block_ranges[block_id] = (min(lower, axis_value), max(upper, axis_value))
        for value in canonical_case_values(materialized, setting):
            case_metadata = metadata.get(value.case_id)
            if case_metadata is None:
                continue
            block_id = str(case_metadata[spec.block_field])
            axis_value = float(case_metadata[spec.axis_field])
            lower, upper = block_ranges[block_id]
            normalized = 0.0 if upper == lower else (axis_value - lower) / (upper - lower)
            oriented = value.value if value.direction == "maximize" else -value.value
            points.append(
                StructuralCurvePoint(
                    value.track,
                    setting,
                    value.family_id,
                    value.method_id,
                    value.metric,
                    value.direction,
                    spec.axis_name,
                    spec.block_name,
                    block_id,
                    value.case_id,
                    axis_value,
                    normalized,
                    value.value,
                    oriented,
                    value.observation_count,
                )
            )
    return tuple(
        sorted(
            points,
            key=lambda row: (
                row.setting,
                row.family_id,
                row.block_id,
                row.axis_value,
                row.case_id,
            ),
        )
    )


def _collapsed_block(
    points: list[StructuralCurvePoint],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    by_axis: dict[float, list[StructuralCurvePoint]] = {}
    for point in points:
        by_axis.setdefault(point.normalized_axis, []).append(point)
    axes = np.asarray(sorted(by_axis), dtype=float)
    raw = np.asarray(
        [mean(point.primary_value for point in by_axis[axis]) for axis in axes],
        dtype=float,
    )
    oriented = np.asarray(
        [mean(point.oriented_value for point in by_axis[axis]) for axis in axes],
        dtype=float,
    )
    return axes, raw, oriented


def summarize_structural_profiles(
    results: Iterable[BenchmarkResult],
) -> tuple[StructuralProfile, ...]:
    """Summarize curves without collapsing performance and robustness into a rank."""

    materialized = tuple(results)
    points = structural_curve_points(materialized)
    expected_blocks = {
        setting: {
            str(case_metadata[spec.block_field])
            for case_metadata in _case_metadata(materialized, spec).values()
        }
        for setting, spec in STRUCTURAL_AXIS_SPECS.items()
    }
    groups: dict[tuple[str, str, str], list[StructuralCurvePoint]] = {}
    for point in points:
        groups.setdefault((point.setting, point.family_id, point.method_id), []).append(point)

    profiles: list[StructuralProfile] = []
    for (setting, family_id, method_id), family_points in sorted(groups.items()):
        by_block: dict[str, list[StructuralCurvePoint]] = {}
        for point in family_points:
            by_block.setdefault(point.block_id, []).append(point)
        block_summaries = []
        nondegrading = 0
        transitions = 0
        retained_points: list[StructuralCurvePoint] = []
        for block_points in by_block.values():
            axes, raw, oriented = _collapsed_block(block_points)
            if len(axes) < 2 or float(axes[-1]) == float(axes[0]):
                continue
            retained_points.extend(block_points)
            differences = np.diff(oriented)
            nondegrading += int(np.sum(differences >= -1e-12))
            transitions += len(differences)
            block_summaries.append(
                (
                    float(np.mean(raw)),
                    float(np.sum((oriented[:-1] + oriented[1:]) * np.diff(axes) / 2)),
                    float(np.polyfit(axes, oriented, 1)[0]),
                    float(oriented[-1] - oriented[0]),
                )
            )
        if not block_summaries:
            continue
        first = family_points[0]
        raw_values = [point.primary_value for point in retained_points]
        expected = len(expected_blocks[setting])
        profiles.append(
            StructuralProfile(
                first.track,
                setting,
                family_id,
                method_id,
                first.primary_metric,
                first.direction,
                first.axis_name,
                first.block_name,
                len({point.case_id for point in retained_points}),
                sum(point.observation_count for point in retained_points),
                len(block_summaries),
                expected,
                len(block_summaries) / expected if expected else 0.0,
                mean(summary[0] for summary in block_summaries),
                min(raw_values) if first.direction == "maximize" else max(raw_values),
                mean(summary[1] for summary in block_summaries),
                mean(summary[2] for summary in block_summaries),
                mean(summary[3] for summary in block_summaries),
                nondegrading / transitions if transitions else 0.0,
            )
        )
    return tuple(profiles)


def _write_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_structural_profile_artifacts(
    results: Iterable[BenchmarkResult], output_dir: str | Path
) -> tuple[Path, Path, Path]:
    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    points = structural_curve_points(materialized)
    profiles = summarize_structural_profiles(materialized)
    point_path = _write_csv(
        destination / "structural_curve_points.csv",
        [point.to_dict() for point in points],
        tuple(StructuralCurvePoint.__dataclass_fields__),
    )
    profile_path = _write_csv(
        destination / "structural_profiles.csv",
        [profile.to_dict() for profile in profiles],
        tuple(StructuralProfile.__dataclass_fields__),
    )
    markdown_path = destination / "structural_profiles.md"
    lines = [
        "# Structural Mechanism Profiles",
        "",
        "These profiles preserve each paper-grounded axis instead of hiding it inside one mean rank.",
        "Axis values are normalized within each block before computing trapezoidal AUC and slope.",
        "Oriented quantities always use higher-is-better signs; a negative slope or endpoint change means degradation as structural stress increases.",
        "No composite rank is produced. Read mean performance, worst case, curve response, and coverage together.",
        "",
    ]
    for setting in STRUCTURAL_AXIS_SPECS:
        setting_profiles = [row for row in profiles if row.setting == setting]
        if not setting_profiles:
            continue
        lines.extend(
            [
                f"## {setting}",
                "",
                "| family | metric | mean | worst case | oriented AUC | oriented slope | endpoint change | nondegradation | block coverage |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for profile in setting_profiles:
            lines.append(
                f"| {profile.family_id} | {profile.primary_metric} | "
                f"{profile.mean_primary:.4f} | {profile.worst_case_primary:.4f} | "
                f"{profile.oriented_axis_auc:.4f} | {profile.oriented_slope:.4f} | "
                f"{profile.oriented_endpoint_change:.4f} | "
                f"{profile.nondegradation_rate:.1%} | {profile.block_count}/{profile.expected_block_count} |"
            )
        lines.append("")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return point_path, profile_path, markdown_path


__all__ = [
    "STRUCTURAL_AXIS_SPECS",
    "StructuralAxisSpec",
    "StructuralCurvePoint",
    "StructuralProfile",
    "structural_curve_points",
    "summarize_structural_profiles",
    "write_structural_profile_artifacts",
]
