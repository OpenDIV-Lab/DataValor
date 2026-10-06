"""Cross-evidence analyses that turn leaderboard signals into research findings.

The ordinary discovery report is deliberately broad: it is useful for finding
anomalies, but each row is still only a candidate.  This module asks four
narrow questions and triangulates case-level outcomes, mechanism structure,
constraint auditability, and claim semantics before emitting a conclusion.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import spearmanr

from .expectations import ExpectationSpec, load_expectations
from .leaderboard import LeaderboardRow
from .metrics import MetricValue
from .models import BenchmarkResult


@dataclass(frozen=True)
class ProcurementAuditabilityRow:
    setting: str
    raw_winners: str
    qualified_winners: str
    raw_mean: float
    qualified_mean: float
    absolute_gap: float
    relative_gap: float
    pass_count: int
    fail_count: int
    not_auditable_count: int
    dominant_blocker: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MarketThicknessRow:
    family_id: str
    case_count: int
    gft_k1: float | None
    gft_k3: float | None
    gft_k6: float | None
    gft_k12: float | None
    change_k1_to_k12: float | None
    first_k_at_80pct: int | None
    first_k_at_90pct: int | None
    inverse_k_loss_r2: float | None
    trade_count_k12: float | None
    capacity_utilization_k12: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReplicationDecompositionRow:
    family_id: str
    case_count: int
    rank_change_factor2: float | None
    rank_change_factor4: float | None
    reward_share_gain_factor2: float | None
    reward_share_gain_factor4: float | None
    score_inflation_factor2: float | None
    score_inflation_factor4: float | None
    characteristic_inflation_factor2: float | None
    characteristic_inflation_factor4: float | None
    worst_case_id: str
    worst_rank_change: float | None
    worst_score_inflation: float | None
    rank_score_spearman: float | None
    rank_share_spearman: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ClaimAggregationRow:
    expectation_id: str
    family_id: str
    setting: str
    claim_kind: str
    metric_id: str
    relation: str
    target: str
    observation_count: int
    run_not_met_count: int
    run_not_met_rate: float
    case_count: int
    case_mean_not_met_count: int
    case_mean_not_met_rate: float
    verdict_shift: bool
    worst_case_id: str
    worst_case_mean: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _number(raw: Any) -> float | None:
    if isinstance(raw, MetricValue):
        if not raw.applicable:
            return None
        raw = raw.value
    elif isinstance(raw, Mapping) and "applicable" in raw:
        if not raw.get("applicable"):
            return None
        raw = raw.get("value")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _canonical_method(rows: Sequence[BenchmarkResult]) -> str:
    kinds = {
        row.method_id: str(row.metadata.get("implementation_kind", "native"))
        for row in rows
    }
    priority = {"native": 0, "external_adapter": 1}
    return min(kinds, key=lambda method: (priority.get(kinds[method], 2), method))


def procurement_auditability_rows(
    rows: Iterable[LeaderboardRow],
) -> tuple[ProcurementAuditabilityRow, ...]:
    """Measure the outcome lost when rankings require auditable constraints.

    This is named an auditability gap rather than a truthfulness price: a
    ``not_auditable`` row often lacks payment/IR outputs and is not a mechanism
    that has been shown to violate those constraints.
    """

    groups: dict[str, list[LeaderboardRow]] = {}
    for row in rows:
        if (
            row.track == "procurement"
            and row.setting.startswith("P-")
            and row.mean is not None
            and row.coverage_ratio == 1.0
        ):
            groups.setdefault(row.setting, []).append(row)
    summaries = []
    for setting, setting_rows in sorted(groups.items()):
        raw = [row for row in setting_rows if row.raw_rank == 1]
        qualified = [
            row for row in setting_rows if row.constraint_qualified_rank == 1
        ]
        if not raw or not qualified:
            continue
        raw_value = max(float(row.mean) for row in raw)
        qualified_value = max(float(row.mean) for row in qualified)
        gap = raw_value - qualified_value
        status_counts = Counter(row.constraint_status for row in setting_rows)
        blockers = Counter(
            token
            for row in setting_rows
            # A blocker explains why a candidate could not be audited.  Keep
            # observed violations in the separate ``fail_count`` rather than
            # mixing two very different causes.
            if row.constraint_status == "not_auditable"
            for token in row.constraint_reason.split(";")
            if token
        )
        summaries.append(
            ProcurementAuditabilityRow(
                setting=setting,
                raw_winners=";".join(sorted(row.family_id for row in raw)),
                qualified_winners=";".join(
                    sorted(row.family_id for row in qualified)
                ),
                raw_mean=raw_value,
                qualified_mean=qualified_value,
                absolute_gap=gap,
                relative_gap=gap / abs(raw_value) if raw_value else 0.0,
                pass_count=status_counts["pass"],
                fail_count=status_counts["fail"],
                not_auditable_count=status_counts["not_auditable"],
                dominant_blocker=(
                    sorted(blockers.items(), key=lambda item: (-item[1], item[0]))[0][0]
                    if blockers
                    else ""
                ),
            )
        )
    return tuple(summaries)


def _case_means(
    rows: Sequence[BenchmarkResult], metric: str
) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for row in rows:
        value = _number(row.metrics.get(metric)) if row.status == "completed" else None
        if value is not None:
            values.setdefault(row.case_id, []).append(value)
    return {case: float(np.mean(items)) for case, items in values.items()}


def _r_squared(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 2 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    design = np.column_stack((np.ones(len(x)), np.asarray(x, dtype=float)))
    coefficients = np.linalg.lstsq(design, np.asarray(y, dtype=float), rcond=None)[0]
    predictions = design @ coefficients
    residual = float(np.sum((np.asarray(y) - predictions) ** 2))
    total = float(np.sum((np.asarray(y) - np.mean(y)) ** 2))
    return 1.0 - residual / total if total > 0 else None


def market_thickness_rows(
    results: Iterable[BenchmarkResult],
    *,
    families: set[str] | None = None,
) -> tuple[MarketThicknessRow, ...]:
    """Decompose thickness response and expose one-trade capacity ceilings."""

    groups: dict[str, list[BenchmarkResult]] = {}
    for row in results:
        family = str(row.metadata.get("method_family", row.method_id))
        if (
            row.metadata.get("benchmark_setting") == "T-MARKET-THICKNESS"
            and row.status == "completed"
            and bool(row.metadata.get("primary_metric_eligible", True))
            and (families is None or family in families)
        ):
            groups.setdefault(family, []).append(row)
    summaries = []
    for family, family_rows in sorted(groups.items()):
        method = _canonical_method(family_rows)
        canonical = [row for row in family_rows if row.method_id == method]
        by_k: dict[int, list[BenchmarkResult]] = {}
        for row in canonical:
            raw_k = row.metadata.get("efficient_trade_count")
            if raw_k is None:
                continue
            by_k.setdefault(int(raw_k), []).append(row)
        gft: dict[int, float] = {}
        trades: dict[int, float] = {}
        case_ids: set[str] = set()
        for k, k_rows in by_k.items():
            case_gft = _case_means(k_rows, "gain_from_trade_ratio")
            case_trades = _case_means(k_rows, "trade_count")
            case_ids.update(case_gft)
            if case_gft:
                gft[k] = float(np.mean(tuple(case_gft.values())))
            if case_trades:
                trades[k] = float(np.mean(tuple(case_trades.values())))
        if not gft:
            continue
        ks = sorted(gft)
        r2 = _r_squared(
            [1.0 / k for k in ks],
            [1.0 - gft[k] for k in ks],
        )
        first80 = next((k for k in ks if gft[k] >= 0.8), None)
        first90 = next((k for k in ks if gft[k] >= 0.9), None)
        k12_trades = trades.get(12)
        summaries.append(
            MarketThicknessRow(
                family_id=family,
                case_count=len(case_ids),
                gft_k1=gft.get(1),
                gft_k3=gft.get(3),
                gft_k6=gft.get(6),
                gft_k12=gft.get(12),
                change_k1_to_k12=(
                    gft[12] - gft[1] if 1 in gft and 12 in gft else None
                ),
                first_k_at_80pct=first80,
                first_k_at_90pct=first90,
                inverse_k_loss_r2=r2,
                trade_count_k12=k12_trades,
                capacity_utilization_k12=(
                    k12_trades / 12.0 if k12_trades is not None else None
                ),
            )
        )
    return tuple(summaries)


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 3 or len(set(left)) < 2 or len(set(right)) < 2:
        return None
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def replication_decomposition_rows(
    results: Iterable[BenchmarkResult],
    *,
    families: set[str] | None = None,
) -> tuple[ReplicationDecompositionRow, ...]:
    """Retain rank, share, score and characteristic attack axes separately."""

    groups: dict[str, list[BenchmarkResult]] = {}
    for row in results:
        family = str(row.metadata.get("method_family", row.method_id))
        factor = row.metadata.get("replication_factor")
        if (
            row.metadata.get("benchmark_setting") == "V-REPLICATION-ROBUSTNESS"
            and row.status == "completed"
            and bool(row.metadata.get("primary_metric_eligible", True))
            and factor in {2, 4}
            and (families is None or family in families)
        ):
            groups.setdefault(family, []).append(row)
    summaries = []
    metrics = {
        "rank": "replication_owner_rank_change",
        "share": "replication_reward_share_gain",
        "score": "replication_score_inflation_ratio",
        "characteristic": "characteristic_replication_inflation_ratio",
    }
    for family, family_rows in sorted(groups.items()):
        method = _canonical_method(family_rows)
        canonical = [row for row in family_rows if row.method_id == method]
        records: list[dict[str, object]] = []
        for row in canonical:
            record: dict[str, object] = {
                "case": row.case_id,
                "factor": int(row.metadata["replication_factor"]),
            }
            record.update({name: _number(row.metrics.get(metric)) for name, metric in metrics.items()})
            records.append(record)
        by_factor: dict[int, dict[str, float | None]] = {}
        for factor in (2, 4):
            selected = [record for record in records if record["factor"] == factor]
            by_factor[factor] = {
                name: (
                    float(np.mean(values))
                    if (values := [float(record[name]) for record in selected if record[name] is not None])
                    else None
                )
                for name in metrics
            }
        rank_records = [record for record in records if record["rank"] is not None]
        worst = sorted(
            rank_records,
            key=lambda record: (-float(record["rank"]), str(record["case"])),
        )[0]
        paired_rank_score = [
            (float(record["rank"]), float(record["score"]))
            for record in records
            if record["rank"] is not None and record["score"] is not None
        ]
        paired_rank_share = [
            (float(record["rank"]), float(record["share"]))
            for record in records
            if record["rank"] is not None and record["share"] is not None
        ]
        summaries.append(
            ReplicationDecompositionRow(
                family_id=family,
                case_count=len({str(record["case"]) for record in records}),
                rank_change_factor2=by_factor[2]["rank"],
                rank_change_factor4=by_factor[4]["rank"],
                reward_share_gain_factor2=by_factor[2]["share"],
                reward_share_gain_factor4=by_factor[4]["share"],
                score_inflation_factor2=by_factor[2]["score"],
                score_inflation_factor4=by_factor[4]["score"],
                characteristic_inflation_factor2=by_factor[2]["characteristic"],
                characteristic_inflation_factor4=by_factor[4]["characteristic"],
                worst_case_id=str(worst["case"]),
                worst_rank_change=float(worst["rank"]),
                worst_score_inflation=(
                    float(worst["score"]) if worst["score"] is not None else None
                ),
                rank_score_spearman=_spearman(
                    [pair[0] for pair in paired_rank_score],
                    [pair[1] for pair in paired_rank_score],
                ),
                rank_share_spearman=_spearman(
                    [pair[0] for pair in paired_rank_share],
                    [pair[1] for pair in paired_rank_share],
                ),
            )
        )
    return tuple(summaries)


def _meets(value: float, spec: ExpectationSpec) -> bool:
    tolerance = spec.tolerance
    if spec.relation == "eq":
        return abs(value - float(spec.target)) <= tolerance
    if spec.relation == "le":
        return value <= float(spec.target) + tolerance
    if spec.relation == "ge":
        return value + tolerance >= float(spec.target)
    if spec.relation == "range":
        lower, upper = spec.target
        return float(lower) - tolerance <= value <= float(upper) + tolerance
    raise ValueError("case-mean analysis requires an absolute numeric relation")


def _violation(value: float, spec: ExpectationSpec) -> float:
    if spec.relation == "eq":
        return abs(value - float(spec.target))
    if spec.relation == "le":
        return value - float(spec.target)
    if spec.relation == "ge":
        return float(spec.target) - value
    lower, upper = (float(item) for item in spec.target)
    return max(lower - value, value - upper)


def claim_aggregation_rows(
    results: Iterable[BenchmarkResult],
    *,
    specs: Iterable[ExpectationSpec] | None = None,
    minimum_cases: int = 2,
) -> tuple[ClaimAggregationRow, ...]:
    """Compare per-run flags with the case-mean estimand used by expected claims."""

    materialized = tuple(results)
    catalog = tuple(specs) if specs is not None else load_expectations()
    summaries = []
    for spec in catalog:
        if spec.relation.startswith("relative_"):
            continue
        candidates = [
            row
            for row in materialized
            if str(row.metadata.get("method_family", row.method_id)) == spec.family_id
            and row.metadata.get("benchmark_setting") == spec.setting
        ]
        if not candidates:
            continue
        method = _canonical_method(candidates)
        observations: dict[str, list[float]] = {}
        for row in candidates:
            assumptions = set(
                str(value)
                for value in row.metadata.get(
                    "case_assumptions", row.metadata.get("assumptions", ())
                )
            )
            if (
                row.method_id != method
                or row.status != "completed"
                or not set(spec.required_assumptions).issubset(assumptions)
            ):
                continue
            value = _number(row.metrics.get(spec.metric_id))
            if value is not None:
                observations.setdefault(row.case_id, []).append(value)
        if len(observations) < minimum_cases:
            continue
        run_values = [value for values in observations.values() for value in values]
        case_means = {
            case: float(np.mean(values)) for case, values in observations.items()
        }
        run_not_met = sum(not _meets(value, spec) for value in run_values)
        case_not_met = sum(not _meets(value, spec) for value in case_means.values())
        worst_case, worst_value = sorted(
            case_means.items(),
            key=lambda item: (-_violation(item[1], spec), item[0]),
        )[0]
        summaries.append(
            ClaimAggregationRow(
                expectation_id=spec.expectation_id,
                family_id=spec.family_id,
                setting=spec.setting,
                claim_kind=spec.claim_kind,
                metric_id=spec.metric_id,
                relation=spec.relation,
                target=str(spec.target),
                observation_count=len(run_values),
                run_not_met_count=run_not_met,
                run_not_met_rate=run_not_met / len(run_values),
                case_count=len(case_means),
                case_mean_not_met_count=case_not_met,
                case_mean_not_met_rate=case_not_met / len(case_means),
                verdict_shift=(run_not_met > 0) != (case_not_met > 0),
                worst_case_id=worst_case,
                worst_case_mean=worst_value,
            )
        )
    return tuple(summaries)


def _write_rows(path: Path, rows: Sequence[object], row_type: type) -> Path:
    fields = tuple(row_type.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    return path


def _fmt(value: float | None, digits: int = 3) -> str:
    return "NA" if value is None else f"{value:.{digits}f}"


def write_deep_dive_artifacts(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    leaderboard_rows: Iterable[LeaderboardRow],
    specs: Iterable[ExpectationSpec] | None = None,
) -> tuple[Path, ...]:
    """Write four reproducible tables and a triangulated research report."""

    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    procurement = procurement_auditability_rows(leaderboard_rows)
    thickness = market_thickness_rows(materialized)
    replication = replication_decomposition_rows(materialized)
    claims = claim_aggregation_rows(materialized, specs=specs)
    paths = (
        _write_rows(destination / "deep_dive_auditability.csv", procurement, ProcurementAuditabilityRow),
        _write_rows(destination / "deep_dive_market_thickness.csv", thickness, MarketThicknessRow),
        _write_rows(destination / "deep_dive_replication.csv", replication, ReplicationDecompositionRow),
        _write_rows(destination / "deep_dive_claim_aggregation.csv", claims, ClaimAggregationRow),
    )

    audit_lines = [
        f"| `{row.setting}` | `{row.raw_winners}` | `{row.qualified_winners}` | {_fmt(row.absolute_gap)} | {row.not_auditable_count} | {row.fail_count} | `{row.dominant_blocker or 'none'}` |"
        for row in procurement
    ] or ["| no eligible setting | | | | | | |"]
    thickness_focus = {
        "bilateral_midpoint",
        "sbba",
        "trade_reduction",
        "vickrey_muda",
        "lottery_muda",
    }
    thickness_lines = [
        f"| `{row.family_id}` | {_fmt(row.gft_k1)} | {_fmt(row.gft_k3)} | {_fmt(row.gft_k6)} | {_fmt(row.gft_k12)} | {_fmt(row.change_k1_to_k12)} | {_fmt(row.inverse_k_loss_r2)} | {_fmt(row.capacity_utilization_k12)} |"
        for row in thickness
        if row.family_id in thickness_focus
    ] or ["| no eligible family | | | | | | | |"]
    replication_focus = {
        "volume_shapley",
        "robust_volume_shapley",
        "data_oob",
        "datainf",
        "tracin_cp",
    }
    replication_lines = [
        f"| `{row.family_id}` | {_fmt(row.rank_change_factor2)} → {_fmt(row.rank_change_factor4)} | {_fmt(row.reward_share_gain_factor2)} → {_fmt(row.reward_share_gain_factor4)} | {_fmt(row.score_inflation_factor2)} → {_fmt(row.score_inflation_factor4)} | `{row.worst_case_id}` | {_fmt(row.rank_score_spearman)} |"
        for row in replication
        if row.family_id in replication_focus
    ] or ["| no eligible family | | | | | |"]
    claim_lines = [
        f"| `{row.expectation_id}` | {row.run_not_met_count}/{row.observation_count} ({row.run_not_met_rate:.1%}) | {row.case_mean_not_met_count}/{row.case_count} ({row.case_mean_not_met_rate:.1%}) | {'yes' if row.verdict_shift else 'no'} | `{row.worst_case_id}` |"
        for row in claims
        if row.run_not_met_count or row.case_mean_not_met_count
    ] or ["| no failed numeric claim | | | | |"]

    largest_audit_gap = max(procurement, key=lambda row: row.absolute_gap, default=None)
    smallest_audit_gap = min(procurement, key=lambda row: row.absolute_gap, default=None)
    thickness_index = {row.family_id: row for row in thickness}
    replication_index = {row.family_id: row for row in replication}
    volume = replication_index.get("volume_shapley")
    robust_volume = replication_index.get("robust_volume_shapley")
    aggregation_shift = next((row for row in claims if row.verdict_shift), None)
    audit_highlight = (
        f"The largest observed gap is `{largest_audit_gap.setting}` at "
        f"{largest_audit_gap.absolute_gap:.3f}; the smallest is "
        f"`{smallest_audit_gap.setting}` at {smallest_audit_gap.absolute_gap:.3f}."
        if largest_audit_gap and smallest_audit_gap
        else "No complete procurement comparison was available."
    )
    thickness_highlight = (
        f"In particular, Bilateral Midpoint falls from "
        f"{thickness_index['bilateral_midpoint'].gft_k1:.3f} to "
        f"{thickness_index['bilateral_midpoint'].gft_k12:.3f} while using only "
        f"{thickness_index['bilateral_midpoint'].capacity_utilization_k12:.1%} of k=12 capacity; "
        f"Trade Reduction rises to {thickness_index['trade_reduction'].gft_k12:.3f} "
        f"with an inverse-k fit of {thickness_index['trade_reduction'].inverse_k_loss_r2:.3f}."
        if {"bilateral_midpoint", "trade_reduction"} <= set(thickness_index)
        else "The CSV retains all eligible thickness curves."
    )
    replication_highlight = (
        f"For Volume Shapley, moving from factor 2 to 4 leaves mean rank gain at "
        f"{volume.rank_change_factor4:.3f} but raises score inflation from "
        f"{volume.score_inflation_factor2:.3f} to {volume.score_inflation_factor4:.3f}. "
        f"Robust Volume Shapley holds the corresponding factor-4 values to "
        f"{robust_volume.rank_change_factor4:.3f} and "
        f"{robust_volume.score_inflation_factor4:.3f}."
        if volume
        and robust_volume
        and volume.rank_change_factor4 is not None
        and volume.score_inflation_factor2 is not None
        and volume.score_inflation_factor4 is not None
        and robust_volume.rank_change_factor4 is not None
        and robust_volume.score_inflation_factor4 is not None
        else "The CSV retains all four attack axes for every eligible family."
    )
    aggregation_highlight = (
        f"`{aggregation_shift.expectation_id}` changes from "
        f"{aggregation_shift.run_not_met_count}/{aggregation_shift.observation_count} "
        f"per-run misses to {aggregation_shift.case_mean_not_met_count}/"
        f"{aggregation_shift.case_count} case-mean misses."
        if aggregation_shift
        else "No run-to-case verdict shift was observed."
    )

    report = destination / "deep_dive_report.md"
    report.write_text(
        "\n".join(
            [
                "# Deep-dive findings: from rankings to mechanism evidence",
                "",
                "This report contains four research findings, not a list of leaderboard observations. Each finding joins multiple evidence layers, states the mechanism-level interpretation, records a competing explanation, and ends with a falsifiable follow-up. The broad `discovery_findings.csv` remains a screening appendix; its rows are not independent scientific conclusions.",
                "",
                "## 1. Procurement has a price of auditability, not yet a measured price of truthfulness",
                "",
                "**Question.** How much objective value is lost when the winner must expose enough information to audit budget feasibility and seller individual rationality?",
                "",
                "| Setting | Raw winner | Auditable winner | objective gap | not auditable | actual fail | dominant blocker |",
                "|---|---|---|---:|---:|---:|---|",
                *audit_lines,
                "",
                f"**Evidence and mechanism explanation.** {audit_highlight} The raw and qualified columns optimize the same case-macro objective; the only change is whether the guardrails can be checked and pass. Large gaps therefore identify settings where strong allocation policies are not packaged as complete payment mechanisms. The distinction between `not_auditable` and `fail` is decisive: missing payment or IR outputs are capability gaps, whereas a failed rule is an observed violation. Calling the whole gap a price of truthfulness would conflate these states.",
                "",
                "**Competing explanation / validity boundary.** An allocation-only winner may admit a truthful, budget-feasible payment rule that is absent from this implementation. Conversely, adding payments can change allocation incentives, so the raw objective is not guaranteed to survive completion. The table measures the empirical price of *requiring an auditable mechanism interface*, not an impossibility bound.",
                "",
                "**Falsifiable next experiment.** Hold the allocation rule fixed, add the paper-consistent payment transformation where one exists, and rerun the same cases. If most of the gap disappears, missing implementation—not an economic trade-off—caused it; if the gap remains after guardrails pass, it becomes evidence of a genuine constrained-efficiency frontier.",
                "",
                "## 2. Market thickness separates three mechanism regimes—and exposes a misleading baseline",
                "",
                "**Question.** Does additional efficient trade capacity improve a mechanism, and at what rate?",
                "",
                "| Family | GFT k=1 | k=3 | k=6 | k=12 | Δ(12−1) | R²: loss~1/k | k=12 capacity use |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
                *thickness_lines,
                "",
                f"**Evidence and mechanism explanation.** {thickness_highlight} The joint trajectory distinguishes (i) one-trade capacity-limited rules, whose ratio falls approximately as 1/k because their numerator cannot scale; (ii) trade-reduction mechanisms, whose one-unit sacrifice becomes negligible as k grows; and (iii) randomized/sample-splitting mechanisms, which improve with thickness but pay finite-market estimation and partition costs. A high inverse-k fit is meaningful only together with trade count and capacity utilization.",
                "",
                "**Competing explanation / validity boundary.** The bilateral midpoint implementation executes one pair by construction. Its declining GFT ratio is therefore an interface-capacity mismatch, not evidence that thicker markets economically harm midpoint pricing. Likewise, perfect results on constructed cases cannot establish general efficiency without distributional and strategic perturbations.",
                "",
                "**Falsifiable next experiment.** Add repeated-bilateral and multi-unit midpoint variants while preserving price formation, then vary both k and surplus-margin heterogeneity. A capacity explanation predicts that repeated matching removes the 1/k collapse; a pricing explanation predicts persistent welfare loss after trade count scales.",
                "",
                "## 3. Replication robustness is not one axis: ranks can saturate while reward extraction explodes",
                "",
                "**Question.** When an owner replicates data, do rank, reward share, raw score and characteristic-function value tell the same story?",
                "",
                "| Family | rank gain f2→f4 | reward-share gain f2→f4 | score inflation f2→f4 | worst rank case | ρ(rank, score) |",
                "|---|---|---|---|---|---:|",
                *replication_lines,
                "",
                f"**Evidence and mechanism explanation.** {replication_highlight} The axes need not agree. Rank is ordinal and bounded: once the attacked owner reaches the top, further score inflation is invisible. Reward share captures normalization against other owners, raw score inflation captures payment-scale exposure, and characteristic inflation asks whether the underlying coalition value itself changed. The factor-2/factor-4 columns and within-case correlations make that decoupling testable instead of collapsing it into one leaderboard number.",
                "",
                "**Competing explanation / validity boundary.** The benchmark replicates an owner bundle under a fixed training/evaluation protocol; it does not cover every identity-splitting or semivalue implementation. Negative mean rank change also does not imply robustness when a method has severe positive tail cases. Claims should therefore be family- and attack-model-specific and include worst-case outcomes.",
                "",
                "**Falsifiable next experiment.** Sweep replication factors beyond four and add partial/near-duplicate attacks. A rank-saturation hypothesis predicts flat ranks with continuing score/share growth; a genuinely replication-robust mechanism predicts all monetary axes remain near their neutral values and worst-case tails do not grow.",
                "",
                "## 4. A paper claim must be evaluated at the claim's aggregation scale",
                "",
                "**Question.** Do per-seed failures survive when a randomized expected guarantee is evaluated over mechanism randomness within each case?",
                "",
                "| Claim | per-run misses | case-mean misses | verdict shift | worst case |",
                "|---|---:|---:|---|---|",
                *claim_lines,
                "",
                f"**Evidence and mechanism explanation.** {aggregation_highlight} A theorem stated in expectation can legitimately produce sub-threshold individual random draws. The per-run column is useful for tail-risk diagnostics, but the case-mean column targets the expected claim. A verdict shift shows that the old row-wise pass/fail summary changed the estimand and could overstate a contradiction. Deterministic pointwise claims, in contrast, should not receive this averaging exemption.",
                "",
                "**Competing explanation / validity boundary.** Finite seeds estimate rather than equal the expectation, and case averaging does not prove the theorem. Sampled regret diagnostics may also measure ex-post deviations of realized randomized allocations while a paper claims ex-ante incentive properties. Those are protocol mismatches to document, not theorem refutations.",
                "",
                "**Falsifiable next experiment.** Give every expectation an explicit aggregation contract (`pointwise`, `expected_over_mechanism`, or `distributional_tail`), pre-register its uncertainty rule, and increase seeds until the case-mean confidence interval is decision-stable. A genuine expected-bound failure must remain below target after this correction.",
                "",
                "## Cross-finding implication",
                "",
                "The benchmark's distinctive unit should be a **claim-aware mechanism profile**, not a single score: an outcome metric is interpreted jointly with implementability constraints, market structure, attack magnitude, and the aggregation semantics of the source claim. The four CSV files make every number above reproducible and permit later methods to be added without rewriting the narrative logic.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return (*paths, report)


__all__ = [
    "ClaimAggregationRow",
    "MarketThicknessRow",
    "ProcurementAuditabilityRow",
    "ReplicationDecompositionRow",
    "claim_aggregation_rows",
    "market_thickness_rows",
    "procurement_auditability_rows",
    "replication_decomposition_rows",
    "write_deep_dive_artifacts",
]
