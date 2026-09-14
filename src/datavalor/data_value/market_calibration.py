"""Grouped, interval, and ranking calibration for realized data value."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .extensions import CalibrationReport, calibrate_values


@dataclass(frozen=True)
class GroupCalibration:
    group: Mapping[str, str]
    calibration: CalibrationReport
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def calibrate_values_by_group(
    observations: Sequence[Mapping[str, Any]],
    group_by: Sequence[str] = ("buyer_id", "task_id", "version"),
    *,
    minimum_observations: int = 2,
) -> tuple[GroupCalibration, ...]:
    """Calibrate estimates within explicit buyer/task/version cohorts."""
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for item in observations:
        try:
            valid = math.isfinite(float(item.get("predicted"))) and math.isfinite(float(item.get("observed")))
        except (TypeError, ValueError):
            valid = False
        if valid:
            grouped[tuple(str(item.get(name, "<missing>")) for name in group_by)].append(item)
    result = []
    for key, items in sorted(grouped.items()):
        if len(items) < minimum_observations:
            continue
        calibration = calibrate_values(
            [item["predicted"] for item in items],
            [item["observed"] for item in items],
        )
        result.append(
            GroupCalibration(
                dict(zip(group_by, key)),
                calibration,
                {"observation_ids": tuple(str(item.get("observation_id", index)) for index, item in enumerate(items))},
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class IntervalCalibrationReport:
    observations: int
    coverage_rate: float
    mean_width: float
    below_interval: int
    above_interval: int
    invalid: int


def evaluate_value_intervals(intervals: Sequence[Mapping[str, Any]]) -> IntervalCalibrationReport:
    """Measure how often realized values fall inside predicted intervals."""
    valid = []; invalid = 0
    for item in intervals:
        try:
            lower, upper, observed = float(item["lower"]), float(item["upper"]), float(item["observed"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if not all(math.isfinite(value) for value in (lower, upper, observed)) or lower > upper:
            invalid += 1
            continue
        valid.append((lower, upper, observed))
    inside = sum(lower <= observed <= upper for lower, upper, observed in valid)
    below = sum(observed < lower for lower, _, observed in valid)
    above = sum(observed > upper for _, upper, observed in valid)
    return IntervalCalibrationReport(
        len(valid),
        inside / len(valid) if valid else 0.0,
        sum(upper - lower for lower, upper, _ in valid) / len(valid) if valid else 0.0,
        below,
        above,
        invalid,
    )


@dataclass(frozen=True)
class RankingCalibrationReport:
    observations: int
    comparable_pairs: int
    concordant_pairs: int
    discordant_pairs: int
    tied_pairs: int
    pairwise_accuracy: float | None


def evaluate_value_ranking(predicted: Sequence[float], observed: Sequence[float]) -> RankingCalibrationReport:
    """Evaluate whether predicted value ordering matches realized ordering."""
    if len(predicted) != len(observed):
        raise ValueError("predicted and observed must have equal length")
    pairs = [(float(left), float(right)) for left, right in zip(predicted, observed)]
    if any(not all(math.isfinite(value) for value in pair) for pair in pairs):
        raise ValueError("ranking values must be finite")
    concordant = discordant = tied = 0
    for left in range(len(pairs)):
        for right in range(left + 1, len(pairs)):
            predicted_delta = pairs[left][0] - pairs[right][0]
            observed_delta = pairs[left][1] - pairs[right][1]
            if predicted_delta == 0 or observed_delta == 0:
                tied += 1
            elif predicted_delta * observed_delta > 0:
                concordant += 1
            else:
                discordant += 1
    comparable = concordant + discordant
    return RankingCalibrationReport(
        len(pairs), comparable, concordant, discordant, tied,
        concordant / comparable if comparable else None,
    )


__all__ = [
    "GroupCalibration", "IntervalCalibrationReport", "RankingCalibrationReport",
    "calibrate_values_by_group", "evaluate_value_intervals", "evaluate_value_ranking",
]
