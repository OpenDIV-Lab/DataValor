"""Controlled support-geometry study for double-auction mechanisms."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Iterable, Sequence

import numpy as np
from scipy.stats import spearmanr

from .metrics import MetricValue, evaluate_trading_metrics
from .models import MarketOutcome, TradeCase
from .runner import build_registry
from .settings.trading import make_market_geometry_cases

GEOMETRY_METHOD_IDS = (
    "mcafee",
    "trade_reduction",
    "sbba",
    "random_sampling_double",
    "lottery_muda",
    "vickrey_muda",
)
DETERMINISTIC_METHOD_IDS = frozenset({"mcafee", "trade_reduction"})
PARTITION_METHOD_IDS = frozenset(
    {"random_sampling_double", "lottery_muda", "vickrey_muda"}
)
GEOMETRY_SEEDS = tuple(range(128))
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEOMETRY_OUTPUT = PACKAGE_ROOT / "outputs" / "kdd_trading_geometry"
DEFAULT_GEOMETRY_CATALOG = PACKAGE_ROOT / "catalog" / "trading_geometry_study.yaml"


@dataclass(frozen=True)
class GeometryRun:
    run_id: str
    method_id: str
    case_id: str
    seed: int
    minimum_efficient_surplus: float
    buyer_margin_share: float
    support_asymmetry: str
    efficient_trade_count: int
    gain_from_trade_ratio: float
    trade_count: int
    capacity_utilization: float
    count_matched_frontier_gft_ratio: float
    capacity_loss_ratio: float
    selection_pricing_loss_ratio: float
    individual_rationality: bool
    weak_budget_balance: bool
    left_price_available: bool | None
    right_price_available: bool | None
    normalized_cross_price_gap: float | None
    efficient_partition_imbalance: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GeometryCellSummary:
    method_id: str
    case_id: str
    minimum_efficient_surplus: float
    buyer_margin_share: float
    support_asymmetry: str
    run_count: int
    randomness_estimand: str
    expected_gft: float
    gft_p10: float
    gft_p90: float
    mean_capacity_utilization: float
    mean_capacity_loss_ratio: float
    mean_selection_pricing_loss_ratio: float
    zero_trade_rate: float
    price_unavailable_rate: float | None
    mean_normalized_cross_price_gap: float | None
    mean_efficient_partition_imbalance: float | None
    imbalance_gft_spearman: float | None
    imbalance_gft_slope: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GeometryEffect:
    method_id: str
    minimum_efficient_surplus: float
    reference_buyer_margin_share: float
    comparison_buyer_margin_share: float
    run_count: int
    mean_gft_difference: float
    difference_p10: float
    difference_p90: float
    interval_scope: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GeometryMethodSummary:
    method_id: str
    cell_count: int
    total_run_count: int
    macro_expected_gft: float
    worst_expected_gft: float
    worst_cell_id: str
    geometry_range: float
    macro_capacity_utilization: float
    macro_capacity_loss_ratio: float
    macro_selection_pricing_loss_ratio: float
    max_selection_pricing_loss_ratio: float
    max_absolute_asymmetry_effect: float
    residual_partition_spearman: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _metric_value(metrics: dict[str, MetricValue] | object, name: str) -> object:
    value = metrics[name]  # type: ignore[index]
    if not isinstance(value, MetricValue) or not value.applicable:
        reason = value.reason if isinstance(value, MetricValue) else "invalid_metric"
        raise ValueError(f"{name} is not applicable: {reason}")
    return value.value


def _partition_imbalance(case: TradeCase, outcome: MarketOutcome) -> float | None:
    if not all(
        key in outcome.diagnostics
        for key in ("left_buyers", "left_sellers", "right_buyers", "right_sellers")
    ):
        return None
    k = int(case.metadata["efficient_trade_count"])
    efficient_buyers = set(
        sorted(case.public.buyer_ids, key=lambda actor: (-case.true_values[actor], actor))[:k]
    )
    efficient_sellers = set(
        sorted(case.public.seller_ids, key=lambda actor: (case.true_costs[actor], actor))[:k]
    )
    left_buyers = set(outcome.diagnostics["left_buyers"])
    left_sellers = set(outcome.diagnostics["left_sellers"])
    right_buyers = set(outcome.diagnostics["right_buyers"])
    right_sellers = set(outcome.diagnostics["right_sellers"])
    numerator = abs(len(left_buyers & efficient_buyers) - len(left_sellers & efficient_sellers))
    numerator += abs(
        len(right_buyers & efficient_buyers) - len(right_sellers & efficient_sellers)
    )
    return numerator / (2 * k)


def _price_diagnostics(
    case: TradeCase, outcome: MarketOutcome
) -> tuple[bool | None, bool | None, float | None]:
    if "left_price" not in outcome.diagnostics or "right_price" not in outcome.diagnostics:
        return None, None, None
    left = outcome.diagnostics["left_price"]
    right = outcome.diagnostics["right_price"]
    if left is None or right is None:
        return left is not None, right is not None, None
    margin = Decimal(str(case.metadata["minimum_efficient_surplus"]))
    return True, True, float(abs(Decimal(left) - Decimal(right)) / margin)


def decompose_trade_loss(
    case: TradeCase,
    *,
    trade_count: int,
    realized_gft_ratio: float,
) -> tuple[float, float, float]:
    """Split GFT loss into count capacity and within-count selection/pricing loss."""

    values = sorted(case.true_values.values(), reverse=True)
    costs = sorted(case.true_costs.values())
    efficient_surpluses = [
        value - cost
        for value, cost in zip(values, costs, strict=True)
        if value >= cost
    ]
    if isinstance(trade_count, bool) or not 0 <= trade_count <= len(efficient_surpluses):
        raise ValueError("trade_count must lie within the efficient single-unit frontier")
    if not math.isfinite(realized_gft_ratio):
        raise ValueError("realized_gft_ratio must be finite")
    oracle = sum(efficient_surpluses, start=Decimal("0"))
    if oracle <= 0:
        raise ValueError("trade-loss decomposition requires positive efficient GFT")
    frontier = float(
        sum(efficient_surpluses[:trade_count], start=Decimal("0")) / oracle
    )
    selection_loss = frontier - realized_gft_ratio
    if selection_loss < -1e-12:
        raise ValueError("realized GFT exceeds the count-matched efficient frontier")
    if selection_loss < 0:
        selection_loss = 0.0
    capacity_loss = 1.0 - frontier
    return frontier, capacity_loss, selection_loss


def run_geometry_study(
    *,
    method_ids: Sequence[str] = GEOMETRY_METHOD_IDS,
    seeds: Sequence[int] = GEOMETRY_SEEDS,
) -> tuple[GeometryRun, ...]:
    """Execute the frozen factorial study without treating seeds as market blocks."""

    requested_methods = tuple(method_ids)
    requested_seeds = tuple(seeds)
    if not requested_methods or len(set(requested_methods)) != len(requested_methods):
        raise ValueError("method_ids must be non-empty and unique")
    if set(requested_methods) - set(GEOMETRY_METHOD_IDS):
        raise ValueError("unsupported geometry-study method")
    if not requested_seeds or len(set(requested_seeds)) != len(requested_seeds):
        raise ValueError("seeds must be non-empty and unique")
    if any(isinstance(seed, bool) or int(seed) != seed or seed < 0 for seed in requested_seeds):
        raise ValueError("seeds must be non-negative integers")

    registry = build_registry()
    cases = make_market_geometry_cases()
    rows: list[GeometryRun] = []
    for case in cases:
        oracle = registry.create("efficient_clearing").clear(case.public, seed=0)
        for method_id in requested_methods:
            method = registry.create(method_id)
            panel = (0,) if method_id in DETERMINISTIC_METHOD_IDS else requested_seeds
            for seed in panel:
                outcome = method.clear(case.public, seed=int(seed))
                metrics = evaluate_trading_metrics(
                    case,
                    outcome,
                    method.spec,
                    oracle,
                    method=None,
                    seed=int(seed),
                )
                gft = float(_metric_value(metrics, "gain_from_trade_ratio"))
                trades = int(_metric_value(metrics, "trade_count"))
                efficient = int(_metric_value(metrics, "efficient_trade_count"))
                frontier, capacity_loss, selection_loss = decompose_trade_loss(
                    case,
                    trade_count=trades,
                    realized_gft_ratio=gft,
                )
                left_available, right_available, price_gap = _price_diagnostics(case, outcome)
                rows.append(
                    GeometryRun(
                        run_id=f"geometry::{method_id}::{case.case_id}::{int(seed)}",
                        method_id=method_id,
                        case_id=case.case_id,
                        seed=int(seed),
                        minimum_efficient_surplus=float(
                            case.metadata["minimum_efficient_surplus"]
                        ),
                        buyer_margin_share=float(case.metadata["buyer_margin_share"]),
                        support_asymmetry=str(case.metadata["support_asymmetry"]),
                        efficient_trade_count=efficient,
                        gain_from_trade_ratio=gft,
                        trade_count=trades,
                        capacity_utilization=trades / efficient,
                        count_matched_frontier_gft_ratio=frontier,
                        capacity_loss_ratio=capacity_loss,
                        selection_pricing_loss_ratio=selection_loss,
                        individual_rationality=bool(
                            _metric_value(metrics, "individual_rationality")
                        ),
                        weak_budget_balance=bool(
                            _metric_value(metrics, "weak_budget_balance")
                        ),
                        left_price_available=left_available,
                        right_price_available=right_available,
                        normalized_cross_price_gap=price_gap,
                        efficient_partition_imbalance=_partition_imbalance(case, outcome),
                    )
                )
    return tuple(sorted(rows, key=lambda row: (row.method_id, row.case_id, row.seed)))


def audit_geometry_runs(
    rows: Iterable[GeometryRun],
    *,
    method_ids: Sequence[str] = GEOMETRY_METHOD_IDS,
    seeds: Sequence[int] = GEOMETRY_SEEDS,
) -> tuple[str, ...]:
    """Fail closed on incomplete panels or invalid study measurements."""

    materialized = tuple(rows)
    seen: set[str] = set()
    for row in materialized:
        if row.run_id in seen:
            return (f"duplicate_run_id:{row.run_id}",)
        seen.add(row.run_id)
    for row in materialized:
        for field in (
            "gain_from_trade_ratio",
            "capacity_utilization",
            "count_matched_frontier_gft_ratio",
            "capacity_loss_ratio",
            "selection_pricing_loss_ratio",
        ):
            if not math.isfinite(float(getattr(row, field))):
                return (f"nonfinite_{field}:{row.run_id}",)
        if not 0.0 <= row.gain_from_trade_ratio <= 1.0 + 1e-12:
            return (f"invalid_gain_from_trade_ratio:{row.run_id}",)
        if not 0.0 <= row.capacity_utilization <= 1.0:
            return (f"invalid_capacity_utilization:{row.run_id}",)
        if not 0.0 <= row.count_matched_frontier_gft_ratio <= 1.0:
            return (f"invalid_count_matched_frontier:{row.run_id}",)
        if not 0.0 <= row.capacity_loss_ratio <= 1.0:
            return (f"invalid_capacity_loss_ratio:{row.run_id}",)
        if row.selection_pricing_loss_ratio < -1e-12:
            return (f"invalid_selection_pricing_loss_ratio:{row.run_id}",)
        if not math.isclose(
            row.capacity_loss_ratio + row.selection_pricing_loss_ratio,
            1.0 - row.gain_from_trade_ratio,
            abs_tol=1e-12,
        ):
            return (f"invalid_trade_loss_decomposition:{row.run_id}",)
        if row.efficient_trade_count != 8:
            return (f"invalid_efficient_trade_count:{row.run_id}",)
        if not row.individual_rationality:
            return (f"individual_rationality_failure:{row.run_id}",)
        if not row.weak_budget_balance:
            return (f"weak_budget_balance_failure:{row.run_id}",)

    case_ids = tuple(case.case_id for case in make_market_geometry_cases())
    expected = {
        f"geometry::{method_id}::{case_id}::{seed}"
        for method_id in method_ids
        for case_id in case_ids
        for seed in ((0,) if method_id in DETERMINISTIC_METHOD_IDS else tuple(seeds))
    }
    actual = {row.run_id for row in materialized}
    errors = [f"missing_run:{run_id}" for run_id in sorted(expected - actual)]
    errors.extend(f"unexpected_run:{run_id}" for run_id in sorted(actual - expected))
    return tuple(errors)


def _association(x: Sequence[float], y: Sequence[float]) -> tuple[float | None, float | None]:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None, None
    rho = float(spearmanr(x, y).statistic)
    slope = float(np.polyfit(np.asarray(x, dtype=float), np.asarray(y, dtype=float), 1)[0])
    if not math.isfinite(rho) or not math.isfinite(slope):
        return None, None
    return rho, slope


def summarize_geometry_cells(
    rows: Iterable[GeometryRun],
) -> tuple[GeometryCellSummary, ...]:
    groups: dict[tuple[str, str], list[GeometryRun]] = defaultdict(list)
    for row in rows:
        groups[(row.method_id, row.case_id)].append(row)
    summaries: list[GeometryCellSummary] = []
    for (method_id, case_id), items in sorted(groups.items()):
        items.sort(key=lambda row: row.seed)
        first = items[0]
        gft = np.asarray([row.gain_from_trade_ratio for row in items], dtype=float)
        imbalance_pairs = [
            (float(row.efficient_partition_imbalance), row.gain_from_trade_ratio)
            for row in items
            if row.efficient_partition_imbalance is not None
        ]
        rho, slope = _association(
            [pair[0] for pair in imbalance_pairs],
            [pair[1] for pair in imbalance_pairs],
        )
        price_rows = [
            row
            for row in items
            if row.left_price_available is not None and row.right_price_available is not None
        ]
        price_gaps = [
            float(row.normalized_cross_price_gap)
            for row in items
            if row.normalized_cross_price_gap is not None
        ]
        summaries.append(
            GeometryCellSummary(
                method_id=method_id,
                case_id=case_id,
                minimum_efficient_surplus=first.minimum_efficient_surplus,
                buyer_margin_share=first.buyer_margin_share,
                support_asymmetry=first.support_asymmetry,
                run_count=len(items),
                randomness_estimand=(
                    "deterministic_point"
                    if method_id in DETERMINISTIC_METHOD_IDS
                    else "conditional_expectation_over_mechanism_seed"
                ),
                expected_gft=float(np.mean(gft)),
                gft_p10=float(np.quantile(gft, 0.10)),
                gft_p90=float(np.quantile(gft, 0.90)),
                mean_capacity_utilization=fmean(row.capacity_utilization for row in items),
                mean_capacity_loss_ratio=fmean(row.capacity_loss_ratio for row in items),
                mean_selection_pricing_loss_ratio=fmean(
                    row.selection_pricing_loss_ratio for row in items
                ),
                zero_trade_rate=fmean(row.trade_count == 0 for row in items),
                price_unavailable_rate=(
                    fmean(
                        not bool(row.left_price_available and row.right_price_available)
                        for row in price_rows
                    )
                    if price_rows
                    else None
                ),
                mean_normalized_cross_price_gap=(fmean(price_gaps) if price_gaps else None),
                mean_efficient_partition_imbalance=(
                    fmean(pair[0] for pair in imbalance_pairs) if imbalance_pairs else None
                ),
                imbalance_gft_spearman=rho,
                imbalance_gft_slope=slope,
            )
        )
    return tuple(summaries)


def paired_geometry_effects(rows: Iterable[GeometryRun]) -> tuple[GeometryEffect, ...]:
    groups: dict[tuple[str, float, float], dict[int, GeometryRun]] = defaultdict(dict)
    for row in rows:
        key = (row.method_id, row.minimum_efficient_surplus, row.buyer_margin_share)
        if row.seed in groups[key]:
            raise ValueError(f"duplicate_effect_seed:{row.method_id}:{row.case_id}:{row.seed}")
        groups[key][row.seed] = row
    methods = sorted({key[0] for key in groups})
    margins = sorted({key[1] for key in groups})
    effects: list[GeometryEffect] = []
    for method_id in methods:
        for margin in margins:
            reference = groups.get((method_id, margin, 0.5))
            if not reference:
                raise ValueError(f"missing_balanced_reference:{method_id}:{margin}")
            for share in (0.2, 0.8):
                comparison = groups.get((method_id, margin, share))
                if not comparison or set(comparison) != set(reference):
                    raise ValueError(f"unmatched_seed_panel:{method_id}:{margin}:{share}")
                differences = np.asarray(
                    [
                        comparison[seed].gain_from_trade_ratio
                        - reference[seed].gain_from_trade_ratio
                        for seed in sorted(reference)
                    ],
                    dtype=float,
                )
                effects.append(
                    GeometryEffect(
                        method_id=method_id,
                        minimum_efficient_surplus=margin,
                        reference_buyer_margin_share=0.5,
                        comparison_buyer_margin_share=share,
                        run_count=len(differences),
                        mean_gft_difference=float(np.mean(differences)),
                        difference_p10=float(np.quantile(differences, 0.10)),
                        difference_p90=float(np.quantile(differences, 0.90)),
                        interval_scope="mechanism_randomness_not_market_sampling",
                    )
                )
    return tuple(effects)


def summarize_geometry_methods(
    cells: Iterable[GeometryCellSummary],
    rows: Iterable[GeometryRun],
) -> tuple[GeometryMethodSummary, ...]:
    cell_groups: dict[str, list[GeometryCellSummary]] = defaultdict(list)
    row_groups: dict[str, list[GeometryRun]] = defaultdict(list)
    materialized_rows = tuple(rows)
    for cell in cells:
        cell_groups[cell.method_id].append(cell)
    for row in materialized_rows:
        row_groups[row.method_id].append(row)
    effect_groups: dict[str, list[GeometryEffect]] = defaultdict(list)
    for effect in paired_geometry_effects(materialized_rows):
        effect_groups[effect.method_id].append(effect)
    summaries: list[GeometryMethodSummary] = []
    for method_id, method_cells in sorted(cell_groups.items()):
        worst = min(method_cells, key=lambda cell: (cell.expected_gft, cell.case_id))
        expected = [cell.expected_gft for cell in method_cells]
        method_rows = row_groups[method_id]
        residual_imbalance: list[float] = []
        residual_gft: list[float] = []
        by_case: dict[str, list[GeometryRun]] = defaultdict(list)
        for row in method_rows:
            by_case[row.case_id].append(row)
        for case_rows in by_case.values():
            eligible = [row for row in case_rows if row.efficient_partition_imbalance is not None]
            if not eligible:
                continue
            mean_imbalance = fmean(float(row.efficient_partition_imbalance) for row in eligible)
            mean_gft = fmean(row.gain_from_trade_ratio for row in eligible)
            residual_imbalance.extend(
                float(row.efficient_partition_imbalance) - mean_imbalance for row in eligible
            )
            residual_gft.extend(row.gain_from_trade_ratio - mean_gft for row in eligible)
        residual_rho, _ = _association(residual_imbalance, residual_gft)
        effects = effect_groups[method_id]
        summaries.append(
            GeometryMethodSummary(
                method_id=method_id,
                cell_count=len(method_cells),
                total_run_count=len(method_rows),
                macro_expected_gft=fmean(expected),
                worst_expected_gft=worst.expected_gft,
                worst_cell_id=worst.case_id,
                geometry_range=max(expected) - min(expected),
                macro_capacity_utilization=fmean(
                    cell.mean_capacity_utilization for cell in method_cells
                ),
                macro_capacity_loss_ratio=fmean(
                    cell.mean_capacity_loss_ratio for cell in method_cells
                ),
                macro_selection_pricing_loss_ratio=fmean(
                    cell.mean_selection_pricing_loss_ratio for cell in method_cells
                ),
                max_selection_pricing_loss_ratio=max(
                    row.selection_pricing_loss_ratio for row in method_rows
                ),
                max_absolute_asymmetry_effect=max(
                    (abs(effect.mean_gft_difference) for effect in effects), default=0.0
                ),
                residual_partition_spearman=residual_rho,
            )
        )
    return tuple(summaries)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: Sequence[object]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty artifact: {path.name}")
    dictionaries = [row.to_dict() for row in rows]  # type: ignore[attr-defined]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(dictionaries[0]))
        writer.writeheader()
        writer.writerows(dictionaries)


def _write_report(
    path: Path,
    methods: Sequence[GeometryMethodSummary],
    effects: Sequence[GeometryEffect],
    findings: dict[str, object],
) -> None:
    lines = [
        "# Trading support-geometry stress study",
        "",
        "This exploratory study fixes 16 buyers, 16 sellers, and eight efficient trades. It varies marginal surplus and which side contributes that surplus; seeds represent mechanism randomness conditional on a controlled cell, not independent markets.",
        "",
        "| method | macro expected GFT | worst cell | worst expected GFT | geometry range | capacity use | capacity loss | selection/pricing loss | max asymmetry effect | residual partition rho |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in methods:
        rho = "N/A" if row.residual_partition_spearman is None else f"{row.residual_partition_spearman:.3f}"
        lines.append(
            f"| `{row.method_id}` | {row.macro_expected_gft:.3f} | `{row.worst_cell_id}` | {row.worst_expected_gft:.3f} | {row.geometry_range:.3f} | {row.macro_capacity_utilization:.3f} | {row.macro_capacity_loss_ratio:.3f} | {row.macro_selection_pricing_loss_ratio:.3f} | {row.max_absolute_asymmetry_effect:.3f} | {rho} |"
        )
    largest = max(effects, key=lambda item: abs(item.mean_gft_difference))
    finding_by_id = {
        str(item["finding_id"]): item
        for item in findings["findings"]  # type: ignore[index]
    }
    if finding_by_id:
        fixed = finding_by_id["fixed_thickness_does_not_fix_geometry_response"]
        partition = finding_by_id["partition_imbalance_tracks_random_halving_loss"]
        capacity = finding_by_id["capacity_does_not_identify_selection_quality"]
        lines.extend(
            [
            "",
            "## Finding 1: fixed thickness does not identify geometry response",
            "",
            f"All cells have k=8 efficient trades. Trade Reduction changes by only {fixed['trade_reduction_geometry_range']:.3f} across the nine cells, while the largest other mechanism range is {fixed['largest_other_geometry_range']:.3f}. Thus the thickness count controls capacity pressure but does not absorb marginal-price and support-shape effects.",
            "",
            "## Finding 2: partition imbalance is a mechanism diagnostic",
            "",
            f"After removing each cell mean, GFT and efficient-trader partition imbalance have residual Spearman correlations from {partition['maximum_residual_partition_spearman']:.3f} to {partition['least_negative_residual_partition_spearman']:.3f} across the three random-halving implementations. This is conditional implementation evidence: imbalance is a diagnostic of the realized split, not an independently randomized market treatment.",
            "",
            "## Finding 3: equal capacity does not imply equal selection quality",
            "",
            f"Lottery- and Vickrey-MUDA have the same macro capacity utilization (difference {capacity['capacity_utilization_difference']:.3f}), yet Lottery-MUDA has {capacity['lottery_minus_vickrey_selection_pricing_loss']:.3f} more count-matched selection/pricing loss. Vickrey-MUDA gains {capacity['vickrey_minus_lottery_macro_gft']:.3f} macro GFT and has {capacity['vickrey_minus_lottery_geometry_range']:.3f} more geometry range. Trade Reduction's maximum selection/pricing loss is {capacity['trade_reduction_max_selection_pricing_loss']:.3g}, empirically isolating its loss to the count-capacity component on these cells. Capacity, allocation quality, and structural fragility must therefore be reported separately.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Cross-mechanism findings unavailable in subset build",
                "",
                "This validation build omits one or more methods required by the frozen six-method finding contract, so it does not emit cross-mechanism conclusions.",
            ]
        )
    lines.extend(
        [
            "",
            "## Largest paired geometry shift",
            "",
            f"The largest same-seed asymmetry effect is {largest.mean_gft_difference:+.3f} for `{largest.method_id}` at minimum surplus {largest.minimum_efficient_surplus:.2f} and buyer margin share {largest.comparison_buyer_margin_share:.1f} relative to 0.5.",
            "The mechanism table separates geometry range from capacity utilization and, where defined, reports within-cell partition sensitivity after case means are removed.",
            "",
            "## Competing explanations and falsifiable follow-up",
            "",
            "The cases are controlled unit-trader specializations. Effects can arise from the selected support family, finite seed panel, or the benchmark implementation boundary; they are not theorem refutations. A follow-up should repeat the frozen design on multi-unit traders and direct data-market type distributions while preserving the same conditional estimands.",
            "",
            "## Claim boundary",
            "",
            "Do not treat seeds as independent markets, call the seed quantiles population confidence intervals, infer DSIC/BIC, or generalize these cells to multi-unit MUDA.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _derive_findings(
    methods: Sequence[GeometryMethodSummary], *, mechanism_seed_count: int
) -> dict[str, object]:
    by_method = {row.method_id: row for row in methods}
    required = set(GEOMETRY_METHOD_IDS)
    missing = sorted(required - set(by_method))
    if missing:
        return {
            "schema_version": "1.0",
            "study_id": "kdd2027-trading-geometry-v1",
            "evidence_tier": "exploratory_controlled_stress",
            "independent_market_count": 0,
            "mechanism_seed_count": mechanism_seed_count,
            "missing_finding_methods": missing,
            "findings": [],
        }
    trade_reduction = by_method["trade_reduction"]
    non_trade_reduction = [
        row.geometry_range for row in methods if row.method_id != "trade_reduction"
    ]
    partition_values = [
        float(by_method[method].residual_partition_spearman)
        for method in ("random_sampling_double", "lottery_muda", "vickrey_muda")
        if by_method[method].residual_partition_spearman is not None
    ]
    lottery = by_method["lottery_muda"]
    vickrey = by_method["vickrey_muda"]
    common = {
        "claim_scope": "controlled_cells_only",
        "heldout_evidence": False,
        "theorem_status": "not_evaluated_by_this_finite_study",
    }
    return {
        "schema_version": "1.0",
        "study_id": "kdd2027-trading-geometry-v1",
        "evidence_tier": "exploratory_controlled_stress",
        "independent_market_count": 0,
        "mechanism_seed_count": mechanism_seed_count,
        "findings": [
            {
                "finding_id": "fixed_thickness_does_not_fix_geometry_response",
                "efficient_trade_count": 8,
                "trade_reduction_geometry_range": trade_reduction.geometry_range,
                "largest_other_geometry_range": max(non_trade_reduction),
                "competing_explanation": "selected support family and implementation branch boundaries",
                **common,
            },
            {
                "finding_id": "partition_imbalance_tracks_random_halving_loss",
                "method_ids": [
                    "random_sampling_double",
                    "lottery_muda",
                    "vickrey_muda",
                ],
                "maximum_residual_partition_spearman": min(partition_values),
                "least_negative_residual_partition_spearman": max(partition_values),
                "competing_explanation": "partition imbalance co-moves with submarket price composition",
                **common,
            },
            {
                "finding_id": "capacity_does_not_identify_selection_quality",
                "method_ids": ["lottery_muda", "vickrey_muda"],
                "capacity_utilization_difference": abs(
                    vickrey.macro_capacity_utilization
                    - lottery.macro_capacity_utilization
                ),
                "vickrey_minus_lottery_macro_gft": (
                    vickrey.macro_expected_gft - lottery.macro_expected_gft
                ),
                "lottery_minus_vickrey_selection_pricing_loss": (
                    lottery.macro_selection_pricing_loss_ratio
                    - vickrey.macro_selection_pricing_loss_ratio
                ),
                "trade_reduction_max_selection_pricing_loss": (
                    trade_reduction.max_selection_pricing_loss_ratio
                ),
                "vickrey_minus_lottery_geometry_range": (
                    vickrey.geometry_range - lottery.geometry_range
                ),
                "competing_explanation": "single-unit specialization and finite seed panel",
                **common,
            },
        ],
    }


def build_geometry_artifacts(
    output_dir: str | Path = DEFAULT_GEOMETRY_OUTPUT,
    *,
    method_ids: Sequence[str] = GEOMETRY_METHOD_IDS,
    seeds: Sequence[int] = GEOMETRY_SEEDS,
) -> dict[str, object]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rows = run_geometry_study(method_ids=method_ids, seeds=seeds)
    errors = audit_geometry_runs(rows, method_ids=method_ids, seeds=seeds)
    if errors:
        raise ValueError(";".join(errors))
    cells = summarize_geometry_cells(rows)
    effects = paired_geometry_effects(rows)
    methods = summarize_geometry_methods(cells, rows)
    findings = _derive_findings(methods, mechanism_seed_count=len(seeds))
    raw_path = destination / "raw_runs.jsonl"
    raw_path.write_text(
        "".join(
            json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    _write_csv(destination / "cell_summary.csv", cells)
    _write_csv(destination / "method_summary.csv", methods)
    _write_csv(destination / "paired_geometry_effects.csv", effects)
    (destination / "findings.json").write_text(
        json.dumps(findings, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_report(destination / "report.md", methods, effects, findings)
    output_names = (
        "raw_runs.jsonl",
        "cell_summary.csv",
        "method_summary.csv",
        "paired_geometry_effects.csv",
        "findings.json",
        "report.md",
    )
    row_counts = {
        "raw_runs.jsonl": len(rows),
        "cell_summary.csv": len(cells),
        "method_summary.csv": len(methods),
        "paired_geometry_effects.csv": len(effects),
        "findings.json": len(findings["findings"]),
        "report.md": None,
    }
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "study_id": "kdd2027-trading-geometry-v1",
        "setting_id": "T-MARKET-GEOMETRY",
        "method_ids": list(method_ids),
        "seeds": list(seeds),
        "deterministic_method_ids": sorted(set(method_ids) & DETERMINISTIC_METHOD_IDS),
        "inference_unit": "controlled_geometry_cell",
        "seed_semantics": "mechanism_randomness_conditional_on_cell",
        "heldout_evidence": False,
        "claim_scope": "exploratory_controlled_support_geometry",
        "design": {
            "buyer_count": 16,
            "seller_count": 16,
            "efficient_trade_count": 8,
            "minimum_efficient_surplus": [0.02, 0.2, 0.6],
            "buyer_margin_share": [0.2, 0.5, 0.8],
        },
        "outputs": {
            name: {
                "sha256": _sha256(destination / name),
                "bytes": (destination / name).stat().st_size,
                "row_count": row_counts[name],
            }
            for name in output_names
        },
        "valid": True,
        "raw_run_count": len(rows),
        "cell_count": len(cells),
        "method_count": len(methods),
        "effect_count": len(effects),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_geometry_artifacts(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return {"errors": ["invalid_outputs_manifest"], "valid": False}
    for name, record in outputs.items():
        artifact = path.parent / name
        if not artifact.is_file():
            errors.append(f"missing_output:{name}")
        elif not isinstance(record, dict) or _sha256(artifact) != record.get("sha256"):
            errors.append(f"sha256_mismatch:{name}")
    return {"errors": errors, "valid": not errors}


__all__ = [
    "DETERMINISTIC_METHOD_IDS",
    "GEOMETRY_METHOD_IDS",
    "GEOMETRY_SEEDS",
    "GeometryCellSummary",
    "GeometryEffect",
    "GeometryMethodSummary",
    "GeometryRun",
    "audit_geometry_runs",
    "build_geometry_artifacts",
    "decompose_trade_loss",
    "paired_geometry_effects",
    "run_geometry_study",
    "summarize_geometry_cells",
    "summarize_geometry_methods",
    "verify_geometry_artifacts",
]
