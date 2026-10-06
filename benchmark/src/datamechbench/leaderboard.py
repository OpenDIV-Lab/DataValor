"""Family-level, case-macro benchmark leaderboard statistics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from .metrics import MetricValue
from .models import BenchmarkResult

PRIMARY_METRICS = {
    "valuation": "score_spearman",
    "procurement": "oracle_ratio",
    "trading": "gain_from_trade_ratio",
}

SETTING_PRIMARY_METRICS = {
    "V-AXIOM": ("score_mae", "minimize"),
    "V-CORRUPTION": ("corruption_auroc", "maximize"),
    "V-CONTRIBUTION": ("utility_recovery", "maximize"),
    "V-UTILITY-NOISE": ("kendall_stability", "maximize"),
    "V-REPLICATION-ROBUSTNESS": ("replication_owner_rank_change", "minimize"),
    "P-ADDITIVE": ("oracle_ratio", "maximize"),
    "P-SUBMODULAR": ("oracle_ratio", "maximize"),
    "P-ML-ACQUISITION": ("oracle_ratio", "maximize"),
    "P-MARKET-CONCENTRATION": ("oracle_ratio", "maximize"),
    "T-BILATERAL": ("gain_from_trade_ratio", "maximize"),
    "T-DOUBLE": ("gain_from_trade_ratio", "maximize"),
    "T-CORRELATED": ("gain_from_trade_ratio", "maximize"),
    "T-NO-TRADE": ("false_trade_count", "minimize"),
    "T-MARKET-THICKNESS": ("gain_from_trade_ratio", "maximize"),
}


@dataclass(frozen=True)
class LeaderboardRow:
    track: str
    setting: str
    scope: str
    family_id: str
    method_id: str
    primary_metric: str
    direction: str
    mean: float | None
    std: float | None
    ci95_low: float | None
    ci95_high: float | None
    case_count: int
    observation_count: int
    rank: int | None
    eligible_case_count: int = 0
    coverage_ratio: float = 0.0
    raw_rank: int | None = None
    qualified_rank: int | None = None
    reason: str = ""
    constraint_status: str = "not_auditable"
    constraint_qualified_rank: int | None = None
    constraint_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MetricStatistic:
    track: str
    setting: str
    scope: str
    family_id: str
    method_id: str
    metric: str
    mean: float
    std: float
    ci95_low: float
    ci95_high: float
    case_count: int
    observation_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CaseMetricValue:
    track: str
    setting: str
    family_id: str
    method_id: str
    metric: str
    direction: str
    case_id: str
    value: float
    observation_count: int


def _scope_filter(
    results: Iterable[BenchmarkResult],
    *,
    include_pilots: bool,
    pilot_only: bool,
    setting: str | None,
    view: str,
) -> tuple[BenchmarkResult, ...]:
    selected = []
    for result in results:
        provenance = str(result.metadata.get("provenance_kind", "paper_variant"))
        if provenance in {"allocation_oracle", "diagnostic_reference"}:
            continue
        if view == "paper" and provenance not in {
            "paper_exact",
            "official_adapter",
            "paper_variant",
            "project_implementation",
        }:
            continue
        if view not in {"all", "paper"}:
            raise ValueError(f"unsupported leaderboard view: {view}")
        is_pilot = bool(result.metadata.get("pilot", False))
        if pilot_only and not is_pilot:
            continue
        if not pilot_only and not include_pilots and is_pilot:
            continue
        if setting is not None and result.metadata.get("benchmark_setting") != setting:
            continue
        selected.append(result)
    return tuple(selected)


def _numeric_metric(result: BenchmarkResult, name: str) -> float | None:
    if result.status != "completed":
        return None
    metric = result.metrics.get(name)
    if isinstance(metric, MetricValue):
        if not metric.applicable:
            return None
        value = metric.value
    else:
        value = metric
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _summary(values: list[float]) -> tuple[float, float, float, float]:
    mean = float(np.mean(values))
    if len(values) == 1:
        return mean, 0.0, mean, mean
    std = float(np.std(values, ddof=1))
    half_width = 1.96 * std / math.sqrt(len(values))
    return mean, std, mean - half_width, mean + half_width


def _canonical_method(rows: Iterable[BenchmarkResult]) -> str:
    candidates: dict[str, str] = {}
    for result in rows:
        candidates[result.method_id] = str(
            result.metadata.get("implementation_kind", "native")
        )
    priority = {"native": 0, "external_adapter": 1}
    return min(
        candidates,
        key=lambda method: (priority.get(candidates[method], 2), method),
    )


def _primary_metric_eligible(result: BenchmarkResult) -> bool:
    return bool(result.metadata.get("primary_metric_eligible", True))


def canonical_case_values(
    results: Iterable[BenchmarkResult],
    setting: str,
    *,
    view: str = "all",
) -> tuple[CaseMetricValue, ...]:
    """Return seed-averaged primary values for each canonical family/case."""

    selected = _scope_filter(
        results,
        include_pilots=False,
        pilot_only=False,
        setting=setting,
        view=view,
    )
    groups: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in selected:
        if result.metadata.get("method_role") == "oracle":
            continue
        family = str(result.metadata.get("method_family", result.method_id))
        groups.setdefault((result.track, family), []).append(result)
    values = []
    for (track, family), family_rows in sorted(groups.items()):
        method_id = _canonical_method(family_rows)
        metric, direction = SETTING_PRIMARY_METRICS.get(
            setting, (PRIMARY_METRICS[track], "maximize")
        )
        by_case: dict[str, list[float]] = {}
        for result in family_rows:
            if result.method_id != method_id or not _primary_metric_eligible(result):
                continue
            value = _numeric_metric(result, metric)
            if value is not None:
                by_case.setdefault(result.case_id, []).append(value)
        for case_id, observations in sorted(by_case.items()):
            values.append(
                CaseMetricValue(
                    track,
                    setting,
                    family,
                    method_id,
                    metric,
                    direction,
                    case_id,
                    float(np.mean(observations)),
                    len(observations),
                )
            )
    return tuple(values)


def summarize_leaderboard(
    results: Iterable[BenchmarkResult],
    *,
    include_pilots: bool,
    setting: str | None = None,
    pilot_only: bool = False,
    view: str = "all",
) -> tuple[LeaderboardRow, ...]:
    """Macro-average the primary metric after selecting one method per family."""

    selected = _scope_filter(
        results,
        include_pilots=include_pilots,
        pilot_only=pilot_only,
        setting=setting,
        view=view,
    )
    family_groups: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in selected:
        if result.metadata.get("method_role") == "oracle":
            continue
        family = str(result.metadata.get("method_family", result.method_id))
        family_groups.setdefault((result.track, family), []).append(result)

    unranked: list[LeaderboardRow] = []
    ranked_by_track: dict[str, list[LeaderboardRow]] = {}
    scope = "pilot" if pilot_only else "stable"
    setting_label = setting or ("pilot" if pilot_only else "all")
    for (track, family), family_rows in sorted(family_groups.items()):
        method_id = _canonical_method(family_rows)
        method_rows = [row for row in family_rows if row.method_id == method_id]
        metric_name, direction = SETTING_PRIMARY_METRICS.get(
            setting_label, (PRIMARY_METRICS[track], "maximize")
        )
        by_case: dict[str, list[float]] = {}
        observation_count = 0
        globally_evaluable = {
            row.case_id
            for row in selected
            if row.track == track
            and _primary_metric_eligible(row)
            and _numeric_metric(row, metric_name) is not None
        }
        eligible_case_count = len(
            {
                row.case_id
                for row in method_rows
                if _primary_metric_eligible(row)
            }.intersection(globally_evaluable)
        )
        for result in method_rows:
            if not _primary_metric_eligible(result):
                continue
            value = _numeric_metric(result, metric_name)
            if value is None:
                continue
            by_case.setdefault(result.case_id, []).append(value)
            observation_count += 1
        case_means = [float(np.mean(values)) for values in by_case.values()]
        if not case_means:
            unranked.append(
                LeaderboardRow(
                    track,
                    setting_label,
                    scope,
                    family,
                    method_id,
                    metric_name,
                    direction,
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                    None,
                    eligible_case_count,
                    0.0,
                    None,
                    None,
                    "no_applicable_primary_metric",
                )
            )
            continue
        mean, std, low, high = _summary(case_means)
        ranked_by_track.setdefault(track, []).append(
            LeaderboardRow(
                track,
                setting_label,
                scope,
                family,
                method_id,
                metric_name,
                direction,
                mean,
                std,
                low,
                high,
                len(case_means),
                observation_count,
                None,
                eligible_case_count,
                len(case_means) / eligible_case_count if eligible_case_count else 0.0,
            )
        )

    ranked: list[LeaderboardRow] = []
    for track, rows in ranked_by_track.items():
        direction = rows[0].direction
        ordered = sorted(
            rows,
            key=lambda row: (
                -float(row.mean) if direction == "maximize" else float(row.mean),
                row.family_id,
            ),
        )
        previous: float | None = None
        previous_rank = 0
        qualified_position = 0
        qualified_previous: float | None = None
        qualified_previous_rank = 0
        for position, row in enumerate(ordered, start=1):
            rounded = round(float(row.mean), 12)
            if previous is None or rounded != previous:
                previous_rank = position
                previous = rounded
            qualified_rank = None
            if row.coverage_ratio == 1.0:
                qualified_position += 1
                if qualified_previous is None or rounded != qualified_previous:
                    qualified_previous_rank = qualified_position
                    qualified_previous = rounded
                qualified_rank = qualified_previous_rank
            ranked.append(
                LeaderboardRow(
                    **{
                        **row.to_dict(),
                        "rank": qualified_rank,
                        "raw_rank": previous_rank,
                        "qualified_rank": qualified_rank,
                        "reason": (
                            row.reason
                            if qualified_rank is not None
                            else "insufficient_case_coverage"
                        ),
                    }
                )
            )
    return tuple(
        sorted(
            (*ranked, *unranked),
            key=lambda row: (
                row.track,
                row.rank is None,
                row.rank if row.rank is not None else math.inf,
                row.family_id,
            ),
        )
    )


def summarize_metrics(results: Iterable[BenchmarkResult]) -> tuple[MetricStatistic, ...]:
    """Return per-method metric summaries with case-level macro weighting."""

    groups: dict[tuple[str, str, str, str, str, str], list[BenchmarkResult]] = {}
    for result in results:
        setting = str(result.metadata.get("benchmark_setting", "unknown"))
        scope = "pilot" if result.metadata.get("pilot", False) else "stable"
        family = str(result.metadata.get("method_family", result.method_id))
        for metric_name in result.metrics:
            key = (result.track, setting, scope, family, result.method_id, metric_name)
            groups.setdefault(key, []).append(result)
        runtime_key = (
            result.track,
            setting,
            scope,
            family,
            result.method_id,
            "wall_runtime_seconds",
        )
        groups.setdefault(runtime_key, []).append(result)

    statistics = []
    for key, rows in sorted(groups.items()):
        by_case: dict[str, list[float]] = {}
        observations = 0
        metric_name = key[-1]
        for result in rows:
            value = (
                result.runtime_seconds
                if metric_name == "wall_runtime_seconds" and result.status == "completed"
                else _numeric_metric(result, metric_name)
            )
            if value is None:
                continue
            by_case.setdefault(result.case_id, []).append(value)
            observations += 1
        if not by_case:
            continue
        case_means = [float(np.mean(values)) for values in by_case.values()]
        mean, std, low, high = _summary(case_means)
        statistics.append(
            MetricStatistic(
                *key,
                mean,
                std,
                low,
                high,
                len(case_means),
                observations,
            )
        )
    return tuple(statistics)


__all__ = [
    "CaseMetricValue",
    "LeaderboardRow",
    "MetricStatistic",
    "PRIMARY_METRICS",
    "SETTING_PRIMARY_METRICS",
    "canonical_case_values",
    "summarize_leaderboard",
    "summarize_metrics",
]
