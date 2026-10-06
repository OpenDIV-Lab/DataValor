"""Declared, metric-compatible assumption-transfer diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .leaderboard import SETTING_PRIMARY_METRICS, LeaderboardRow, summarize_leaderboard
from .models import BenchmarkResult
from .qualification import attach_constraint_ranks, summarize_constraint_profiles
from .resources import resource_path

CATALOG_DIR = resource_path("catalog")
DEFAULT_TRANSFERS = CATALOG_DIR / "assumption_transfers.yaml"
TRACK_PREFIX = {"valuation": "V-", "procurement": "P-", "trading": "T-"}


@dataclass(frozen=True)
class AssumptionTransferSpec:
    transfer_id: str
    track: str
    source_setting: str
    target_setting: str
    primary_metric: str
    direction: str
    rationale: str


@dataclass(frozen=True)
class AssumptionTransferRow:
    transfer_id: str
    track: str
    family_id: str
    source_setting: str
    target_setting: str
    primary_metric: str
    direction: str
    source_mean: float | None
    target_mean: float | None
    oriented_delta: float | None
    source_rank: int | None
    target_rank: int | None
    rank_change: int | None
    source_coverage: float | None
    target_coverage: float | None
    source_constraint_status: str
    target_constraint_status: str
    status: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_assumption_transfers(
    path: str | Path = DEFAULT_TRANSFERS,
) -> tuple[AssumptionTransferSpec, ...]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    seen: set[str] = set()
    specs = []
    for item in raw.get("transfers", ()):
        transfer_id = str(item.get("transfer_id", ""))
        if not transfer_id or transfer_id in seen:
            raise ValueError(f"missing or duplicate transfer_id: {transfer_id!r}")
        seen.add(transfer_id)
        track = str(item.get("track", ""))
        if track not in TRACK_PREFIX:
            raise ValueError(f"transfer {transfer_id} has invalid track {track!r}")
        source = str(item.get("source_setting", ""))
        target = str(item.get("target_setting", ""))
        unknown = [setting for setting in (source, target) if setting not in SETTING_PRIMARY_METRICS]
        if unknown:
            raise ValueError(f"transfer {transfer_id} has unknown setting: {', '.join(unknown)}")
        if not source.startswith(TRACK_PREFIX[track]) or not target.startswith(TRACK_PREFIX[track]):
            raise ValueError(f"transfer {transfer_id} settings do not belong to track {track}")
        source_metric, source_direction = SETTING_PRIMARY_METRICS[source]
        target_metric, target_direction = SETTING_PRIMARY_METRICS[target]
        if source_metric != target_metric:
            raise ValueError(
                f"transfer {transfer_id} primary metric mismatch: {source_metric} != {target_metric}"
            )
        if source_direction != target_direction:
            raise ValueError(
                f"transfer {transfer_id} direction mismatch: {source_direction} != {target_direction}"
            )
        rationale = str(item.get("rationale", "")).strip()
        if not rationale:
            raise ValueError(f"transfer {transfer_id} requires a rationale")
        specs.append(
            AssumptionTransferSpec(
                transfer_id,
                track,
                source,
                target,
                source_metric,
                source_direction,
                rationale,
            )
        )
    if not specs:
        raise ValueError("assumption transfer catalog is empty")
    return tuple(specs)


def _setting_rows(
    results: tuple[BenchmarkResult, ...], setting: str
) -> dict[str, LeaderboardRow]:
    rows = summarize_leaderboard(
        results,
        include_pilots=False,
        setting=setting,
        view="all",
    )
    profiles = summarize_constraint_profiles(results)
    return {
        row.family_id: row
        for row in attach_constraint_ranks(rows, profiles)
    }


def summarize_assumption_transfers(
    results: Iterable[BenchmarkResult],
    *,
    specs: Iterable[AssumptionTransferSpec] | None = None,
) -> tuple[AssumptionTransferRow, ...]:
    materialized = tuple(results)
    selected_specs = tuple(specs) if specs is not None else load_assumption_transfers()
    output = []
    for spec in selected_specs:
        source_rows = _setting_rows(materialized, spec.source_setting)
        target_rows = _setting_rows(materialized, spec.target_setting)
        for family in sorted(set(source_rows) | set(target_rows)):
            source = source_rows.get(family)
            target = target_rows.get(family)
            if source is None:
                status = "missing_source"
            elif target is None:
                status = "missing_target"
            else:
                status = "matched"
            delta = None
            if source is not None and target is not None and source.mean is not None and target.mean is not None:
                raw_delta = float(target.mean) - float(source.mean)
                delta = raw_delta if spec.direction == "maximize" else -raw_delta
            rank_change = None
            if source is not None and target is not None and source.qualified_rank is not None and target.qualified_rank is not None:
                rank_change = target.qualified_rank - source.qualified_rank
            output.append(
                AssumptionTransferRow(
                    spec.transfer_id,
                    spec.track,
                    family,
                    spec.source_setting,
                    spec.target_setting,
                    spec.primary_metric,
                    spec.direction,
                    source.mean if source else None,
                    target.mean if target else None,
                    delta,
                    source.qualified_rank if source else None,
                    target.qualified_rank if target else None,
                    rank_change,
                    source.coverage_ratio if source else None,
                    target.coverage_ratio if target else None,
                    source.constraint_status if source else "missing",
                    target.constraint_status if target else "missing",
                    status,
                    spec.rationale,
                )
            )
    return tuple(output)


__all__ = [
    "AssumptionTransferRow",
    "AssumptionTransferSpec",
    "load_assumption_transfers",
    "summarize_assumption_transfers",
]
