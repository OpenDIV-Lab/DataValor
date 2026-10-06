"""Aggregate-anchor-compatible type profiles for double-auction stress tests."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import yaml

from .metrics import MetricValue, evaluate_trading_metrics
from .models import TradeCase, TradeInput
from .runner import build_registry

HEADLINE_METHOD_IDS = (
    "mcafee",
    "trade_reduction",
    "sbba",
    "lottery_muda",
    "vickrey_muda",
)
ENVELOPE_METHOD_IDS = (
    *HEADLINE_METHOD_IDS,
    "vcg_double_auction",
    "pay_as_bid_double",
    "seller_price_double",
    "midpoint_double",
    "buyer_price_double",
    "random_sampling_double",
)
POSITIONS = ("lower", "midpoint", "upper")
EVIDENCE_SCOPE = "aggregate_anchor_compatible_model_stress"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PACKAGE_ROOT / "catalog" / "aggregate_type_envelope.yaml"
DEFAULT_OUTPUT = PACKAGE_ROOT / "outputs" / "kdd_aggregate_type_envelope"
DEFAULT_FINITE_AUDIT = (
    PACKAGE_ROOT / "outputs" / "kdd_finite_incentives" / "audit_results.json"
)
OUTPUT_NAMES = (
    "raw_runs.jsonl",
    "profile_method_summary.csv",
    "method_robustness_summary.csv",
    "headline_regret_summary.csv",
    "point_selection_transfer.csv",
    "selection_view_profile.csv",
    "selection_view_summary.csv",
    "joint_admissibility.csv",
    "admissibility_relaxation_frontier.csv",
    "rank_reversals.csv",
    "all_method_rank_reversals.csv",
    "findings.json",
    "report.md",
)


@dataclass(frozen=True)
class AggregateTypeRun:
    run_id: str
    method_id: str
    case_id: str
    seed: int
    comparison_group: str
    provenance_kind: str
    seller_position: str
    buyer_position: str
    gain_from_trade_ratio: float
    trade_count: int
    efficient_trade_count: int
    individual_rationality: bool
    weak_budget_balance: bool
    strong_budget_balance: bool | None
    evidence_scope: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeCellSummary:
    method_id: str
    case_id: str
    comparison_group: str
    provenance_kind: str
    seller_position: str
    buyer_position: str
    run_count: int
    expected_gft: float
    gft_p10: float
    gft_p90: float
    mean_trade_count: float
    efficient_trade_count: int
    individual_rationality_rate: float
    weak_budget_balance_rate: float
    strong_budget_balance_rate: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeMethodSummary:
    method_id: str
    comparison_group: str
    provenance_kind: str
    profile_count: int
    total_run_count: int
    macro_expected_gft: float
    worst_profile_gft: float
    best_profile_gft: float
    sensitivity_range: float
    worst_profile_id: str
    best_profile_id: str
    minimum_ir_rate: float
    minimum_weak_budget_balance_rate: float
    minimum_strong_budget_balance_rate: float | None
    weak_budget_balance_profile_pass_count: int
    strong_budget_balance_profile_pass_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeRankReversal:
    method_a: str
    method_b: str
    minimum_difference: float
    minimum_profile_id: str
    maximum_difference: float
    maximum_profile_id: str
    comparison_metric: str = "profile_expected_gft"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeRegretSummary:
    method_id: str
    profile_count: int
    macro_profile_regret: float
    worst_profile_regret: float
    worst_profile_id: str
    minimax_selected: bool
    comparison_scope: str = "headline_reference_expected_gft"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeSelectionTransferSummary:
    selection_profile_id: str
    selected_method_ids: str
    selected_method_count: int
    target_profile_count: int
    mean_optimistic_transfer_regret: float
    worst_optimistic_transfer_regret: float
    worst_optimistic_target_profile_id: str
    mean_pessimistic_transfer_regret: float
    worst_pessimistic_transfer_regret: float
    worst_pessimistic_target_profile_id: str
    optimistically_minimax_robust: bool
    pessimistically_minimax_robust: bool
    comparison_scope: str = "headline_point_profile_selection_expected_gft"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeSelectionViewProfile:
    view_id: str
    view_label: str
    profile_id: str
    eligible_method_ids: str
    eligible_method_count: int
    winner_ids: str
    winner_count: int
    best_expected_gft: float
    unrestricted_best_expected_gft: float
    shortfall_vs_unrestricted: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeSelectionViewSummary:
    view_id: str
    view_label: str
    profile_count: int
    eligible_method_count: int
    eligible_method_union_ids: str
    eligible_method_intersection_ids: str
    winner_union_ids: str
    winner_intersection_ids: str
    macro_best_expected_gft: float
    worst_profile_best_expected_gft: float
    max_shortfall_vs_unrestricted: float
    worst_profile_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeJointAdmissibility:
    method_id: str
    provenance_kind: str
    profile_count: int
    paper_exact: bool
    individual_rationality_all_profiles: bool
    weak_budget_balance_all_profiles: bool
    strong_budget_balance_applicable_all_profiles: bool
    strong_budget_balance_all_profiles: bool
    finite_audit_conclusion: str
    finite_audit_estimand: str
    finite_report_domain_complete: bool
    finite_type_domain_complete: bool
    finite_random_support_complete: bool
    finite_no_counterexample_on_declared_estimand: bool
    joint_admissible: bool
    exclusion_reasons: str
    evidence_boundary: str = (
        "finite no-counterexample evidence applies only to the declared report/type "
        "domain and seed estimand; it is not a strategyproofness theorem"
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AggregateTypeAdmissibilityRelaxation:
    relaxation_id: str
    relaxed_requirement: str
    admitted_method_count: int
    admitted_method_ids: str
    frontier_status: str
    profile_count: int
    macro_best_expected_gft: float | None
    worst_profile_best_expected_gft: float | None
    max_shortfall_vs_headline_best: float | None
    worst_headline_shortfall_profile_id: str
    max_shortfall_vs_unrestricted: float | None
    worst_unrestricted_shortfall_profile_id: str
    evidence_boundary: str = (
        "leave-one-requirement-out diagnostic; relaxing a gate is not a "
        "deployment recommendation or a theoretical property claim"
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _method_contracts(catalog: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    raw = catalog.get("evaluation_methods")
    if not isinstance(raw, list):
        raise ValueError("evaluation_methods must be a list")
    contracts: dict[str, dict[str, str]] = {}
    allowed_groups = {
        "headline_reference",
        "canonical_guardrail",
        "pricing_baseline",
        "diagnostic_reference",
    }
    for index, item in enumerate(raw):
        row = _mapping(item, f"evaluation_methods[{index}]")
        method_id = str(row.get("method_id", "")).strip()
        group = str(row.get("comparison_group", "")).strip()
        provenance = str(row.get("provenance_kind", "")).strip()
        references = row.get("reference_keys")
        if not method_id or method_id in contracts:
            raise ValueError("evaluation method IDs must be non-empty and unique")
        if group not in allowed_groups:
            raise ValueError(f"unsupported comparison group for {method_id}: {group}")
        if not provenance:
            raise ValueError(f"missing provenance_kind for {method_id}")
        if not isinstance(references, list) or not references:
            raise ValueError(f"reference_keys must be non-empty for {method_id}")
        contracts[method_id] = {
            "comparison_group": group,
            "provenance_kind": provenance,
        }
    if tuple(contracts) != ENVELOPE_METHOD_IDS:
        raise ValueError("evaluation_methods must match the frozen envelope method order")
    if tuple(
        method_id
        for method_id, contract in contracts.items()
        if contract["comparison_group"] == "headline_reference"
    ) != HEADLINE_METHOD_IDS:
        raise ValueError("headline_reference methods must match the frozen headline set")
    return contracts


def _curve(
    catalog: Mapping[str, Any],
    key: str,
    *,
    increasing: bool,
) -> tuple[tuple[Decimal, Decimal], ...]:
    raw = catalog.get(key)
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError(f"{key} must contain at least two anchors")
    points: list[tuple[Decimal, Decimal]] = []
    for index, item in enumerate(raw):
        row = _mapping(item, f"{key}[{index}]")
        price = Decimal(str(row["price_eur_month"]))
        share = Decimal(str(row["share_accepting"]))
        if not price.is_finite() or price <= 0:
            raise ValueError(f"invalid price in {key}[{index}]")
        if not share.is_finite() or not Decimal("0") <= share <= Decimal("1"):
            raise ValueError(f"invalid share in {key}[{index}]")
        points.append((price, share))
    if [price for price, _ in points] != sorted(price for price, _ in points):
        raise ValueError(f"{key} prices must be strictly increasing")
    shares = [share for _, share in points]
    expected = sorted(shares, reverse=not increasing)
    if shares != expected or len(set(shares)) != len(shares):
        direction = "increasing" if increasing else "decreasing"
        raise ValueError(f"{key} shares must be strictly {direction}")
    return tuple(points)


def _integer_count(share: Decimal, units: int, label: str) -> int:
    count = share * units
    if count != count.to_integral_value():
        raise ValueError(f"{label} does not map to an integer quantile count")
    return int(count)


def _interval_values(
    low: Decimal,
    high: Decimal,
    position: str,
    *,
    count: int,
    low_open: bool,
    high_open: bool,
    epsilon: Decimal,
) -> tuple[Decimal, ...]:
    if count < 0:
        raise ValueError("interval count must be non-negative")
    if count == 0:
        return ()
    effective_low = low + epsilon if low_open else low
    effective_high = high - epsilon if high_open else high
    if effective_low >= effective_high:
        raise ValueError("interval is empty after open-boundary adjustment")
    midpoint = (effective_low + effective_high) / 2
    if position == "lower":
        start, end = effective_low, midpoint
    elif position == "midpoint":
        start, end = effective_low, effective_high
    elif position == "upper":
        start, end = midpoint, effective_high
    else:
        raise ValueError(f"unsupported interval position: {position}")
    width = end - start
    denominator = Decimal(count)
    return tuple(
        start + width * (Decimal(index) + Decimal("0.5")) / denominator
        for index in range(count)
    )


def _seller_asks(
    curve: tuple[tuple[Decimal, Decimal], ...],
    *,
    units: int,
    position: str,
    epsilon: Decimal,
) -> tuple[Decimal, ...]:
    asks: list[Decimal] = []
    previous_price = Decimal("0")
    previous_share = Decimal("0")
    for price, share in curve:
        count = _integer_count(share - previous_share, units, "seller share")
        asks.extend(
            _interval_values(
                previous_price,
                price,
                position,
                count=count,
                low_open=previous_price > 0,
                high_open=False,
                epsilon=epsilon,
            )
        )
        previous_price = price
        previous_share = share
    return tuple(sorted(asks))


def _buyer_bids(
    curve: tuple[tuple[Decimal, Decimal], ...],
    *,
    units: int,
    position: str,
    epsilon: Decimal,
) -> tuple[Decimal, ...]:
    bids: list[Decimal] = []
    first_price, first_share = curve[0]
    below_count = _integer_count(Decimal("1") - first_share, units, "buyer share")
    bids.extend(
        _interval_values(
            Decimal("0"),
            first_price,
            position,
            count=below_count,
            low_open=False,
            high_open=True,
            epsilon=epsilon,
        )
    )
    for (low, low_share), (high, high_share) in zip(curve, curve[1:]):
        count = _integer_count(low_share - high_share, units, "buyer share")
        bids.extend(
            _interval_values(
                low,
                high,
                position,
                count=count,
                low_open=False,
                high_open=True,
                epsilon=epsilon,
            )
        )
    top_price, top_share = curve[-1]
    bids.extend([top_price] * _integer_count(top_share, units, "buyer top share"))
    return tuple(sorted(bids, reverse=True))


def build_aggregate_type_cases(catalog: Mapping[str, Any]) -> tuple[TradeCase, ...]:
    """Build nine sensitivity profiles without constructing respondent rows."""

    if catalog.get("evidence_scope") != EVIDENCE_SCOPE:
        raise ValueError("aggregate type catalog has an invalid evidence scope")
    source = _mapping(catalog.get("source"), "source")
    construction = _mapping(catalog.get("construction"), "construction")
    units = int(construction["quantile_units"])
    if units <= 0:
        raise ValueError("quantile_units must be positive")
    epsilon = Decimal(str(construction["open_interval_epsilon"]))
    if not epsilon.is_finite() or epsilon <= 0:
        raise ValueError("open_interval_epsilon must be positive and finite")
    declared_positions = tuple(str(item) for item in construction["within_interval_positions"])
    if declared_positions != POSITIONS:
        raise ValueError("within_interval_positions must be lower/midpoint/upper")
    seller_curve = _curve(catalog, "seller_acceptance_curve", increasing=True)
    buyer_curve = _curve(catalog, "buyer_acceptance_curve", increasing=False)
    if tuple(price for price, _ in seller_curve) != tuple(price for price, _ in buyer_curve):
        raise ValueError("seller and buyer anchors must use the same prices")

    cases: list[TradeCase] = []
    for seller_position in POSITIONS:
        asks = _seller_asks(
            seller_curve,
            units=units,
            position=seller_position,
            epsilon=epsilon,
        )
        seller_ids = tuple(f"s{index:03d}" for index in range(len(asks)))
        ask_map = dict(zip(seller_ids, asks))
        for buyer_position in POSITIONS:
            bids = _buyer_bids(
                buyer_curve,
                units=units,
                position=buyer_position,
                epsilon=epsilon,
            )
            buyer_ids = tuple(f"b{index:03d}" for index in range(len(bids)))
            bid_map = dict(zip(buyer_ids, bids))
            case_id = f"TAGG-s{seller_position}-b{buyer_position}"
            metadata = {
                "setting_id": str(catalog["setting_id"]),
                "study_id": str(catalog["study_id"]),
                "seller_position": seller_position,
                "buyer_position": buyer_position,
                "source_sample_size": int(source["sample_size"]),
                "source_reported_never_sell_share": float(
                    source["reported_never_sell_share"]
                ),
                "unresolved_seller_share": float(Decimal("1") - seller_curve[-1][1]),
                "not_microdata": True,
                "evidence_scope": EVIDENCE_SCOPE,
            }
            public = TradeInput(
                product_id="personal-data-use-right-month",
                buyer_ids=buyer_ids,
                seller_ids=seller_ids,
                bids=bid_map,
                asks=ask_map,
                metadata=metadata,
            )
            cases.append(
                TradeCase(
                    case_id=case_id,
                    public=public,
                    true_values=bid_map,
                    true_costs=ask_map,
                    case_type="aggregate_calibrated_interval_profile",
                    metadata=metadata,
                )
            )
    return tuple(cases)


def _metric(metrics: Mapping[str, MetricValue], name: str) -> object:
    value = metrics[name]
    if not value.applicable:
        raise ValueError(f"metric {name} unavailable: {value.reason}")
    return value.value


def _optional_metric(metrics: Mapping[str, MetricValue], name: str) -> bool | None:
    value = metrics[name]
    return bool(value.value) if value.applicable else None


def run_aggregate_type_envelope(
    catalog: Mapping[str, Any],
    *,
    method_ids: Sequence[str] = ENVELOPE_METHOD_IDS,
    seeds: Sequence[int] = tuple(range(32)),
) -> tuple[AggregateTypeRun, ...]:
    """Run headline double-auction mechanisms on the declared sensitivity grid."""

    requested_methods = tuple(method_ids)
    requested_seeds = tuple(int(seed) for seed in seeds)
    if not requested_methods or len(set(requested_methods)) != len(requested_methods):
        raise ValueError("method_ids must be non-empty and unique")
    if set(requested_methods) - set(ENVELOPE_METHOD_IDS):
        raise ValueError("unsupported aggregate-envelope method")
    if not requested_seeds or len(set(requested_seeds)) != len(requested_seeds):
        raise ValueError("seeds must be non-empty and unique")
    if any(seed < 0 for seed in requested_seeds):
        raise ValueError("seeds must be non-negative")

    contracts = _method_contracts(catalog)
    registry = build_registry()
    rows: list[AggregateTypeRun] = []
    for case in build_aggregate_type_cases(catalog):
        oracle = registry.create("efficient_clearing").clear(case.public, seed=0)
        for method_id in requested_methods:
            method = registry.create(method_id)
            panel = requested_seeds if method.spec.stochastic else (requested_seeds[0],)
            for seed in panel:
                outcome = method.clear(case.public, seed=seed)
                metrics = evaluate_trading_metrics(
                    case,
                    outcome,
                    method.spec,
                    oracle,
                    method=None,
                    seed=seed,
                )
                rows.append(
                    AggregateTypeRun(
                        run_id=f"aggregate-envelope::{method_id}::{case.case_id}::{seed}",
                        method_id=method_id,
                        case_id=case.case_id,
                        seed=seed,
                        comparison_group=contracts[method_id]["comparison_group"],
                        provenance_kind=contracts[method_id]["provenance_kind"],
                        seller_position=str(case.metadata["seller_position"]),
                        buyer_position=str(case.metadata["buyer_position"]),
                        gain_from_trade_ratio=float(
                            _metric(metrics, "gain_from_trade_ratio")
                        ),
                        trade_count=int(_metric(metrics, "trade_count")),
                        efficient_trade_count=int(
                            _metric(metrics, "efficient_trade_count")
                        ),
                        individual_rationality=bool(
                            _metric(metrics, "individual_rationality")
                        ),
                        weak_budget_balance=bool(
                            _metric(metrics, "weak_budget_balance")
                        ),
                        strong_budget_balance=_optional_metric(
                            metrics, "strong_budget_balance"
                        ),
                        evidence_scope=EVIDENCE_SCOPE,
                    )
                )
    return tuple(sorted(rows, key=lambda row: (row.method_id, row.case_id, row.seed)))


def summarize_aggregate_type_cells(
    rows: Iterable[AggregateTypeRun],
) -> tuple[AggregateTypeCellSummary, ...]:
    """Aggregate mechanism randomness within each profile, never across profiles."""

    groups: dict[tuple[str, str], list[AggregateTypeRun]] = defaultdict(list)
    for row in rows:
        groups[(row.method_id, row.case_id)].append(row)
    summaries: list[AggregateTypeCellSummary] = []
    for (method_id, case_id), items in sorted(groups.items()):
        first = items[0]
        if any(
            item.seller_position != first.seller_position
            or item.buyer_position != first.buyer_position
            or item.comparison_group != first.comparison_group
            or item.provenance_kind != first.provenance_kind
            for item in items
        ):
            raise ValueError(f"profile metadata mismatch:{method_id}:{case_id}")
        gft = np.asarray([item.gain_from_trade_ratio for item in items], dtype=float)
        strong = [item.strong_budget_balance for item in items]
        summaries.append(
            AggregateTypeCellSummary(
                method_id=method_id,
                case_id=case_id,
                comparison_group=first.comparison_group,
                provenance_kind=first.provenance_kind,
                seller_position=first.seller_position,
                buyer_position=first.buyer_position,
                run_count=len(items),
                expected_gft=float(np.mean(gft)),
                gft_p10=float(np.quantile(gft, 0.10)),
                gft_p90=float(np.quantile(gft, 0.90)),
                mean_trade_count=fmean(item.trade_count for item in items),
                efficient_trade_count=first.efficient_trade_count,
                individual_rationality_rate=fmean(
                    float(item.individual_rationality) for item in items
                ),
                weak_budget_balance_rate=fmean(
                    float(item.weak_budget_balance) for item in items
                ),
                strong_budget_balance_rate=(
                    fmean(float(value) for value in strong if value is not None)
                    if all(value is not None for value in strong)
                    else None
                ),
            )
        )
    return tuple(summaries)


def summarize_aggregate_type_methods(
    cells: Iterable[AggregateTypeCellSummary],
) -> tuple[AggregateTypeMethodSummary, ...]:
    """Report sensitivity ranges without treating profiles as sampled blocks."""

    groups: dict[str, list[AggregateTypeCellSummary]] = defaultdict(list)
    for cell in cells:
        groups[cell.method_id].append(cell)
    summaries: list[AggregateTypeMethodSummary] = []
    for method_id, items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: (item.expected_gft, item.case_id))
        worst = ordered[0]
        best = ordered[-1]
        if any(
            item.comparison_group != worst.comparison_group
            or item.provenance_kind != worst.provenance_kind
            for item in items
        ):
            raise ValueError(f"method contract mismatch:{method_id}")
        strong_rates = [
            item.strong_budget_balance_rate
            for item in items
            if item.strong_budget_balance_rate is not None
        ]
        summaries.append(
            AggregateTypeMethodSummary(
                method_id=method_id,
                comparison_group=worst.comparison_group,
                provenance_kind=worst.provenance_kind,
                profile_count=len(items),
                total_run_count=sum(item.run_count for item in items),
                macro_expected_gft=fmean(item.expected_gft for item in items),
                worst_profile_gft=worst.expected_gft,
                best_profile_gft=best.expected_gft,
                sensitivity_range=best.expected_gft - worst.expected_gft,
                worst_profile_id=worst.case_id,
                best_profile_id=best.case_id,
                minimum_ir_rate=min(item.individual_rationality_rate for item in items),
                minimum_weak_budget_balance_rate=min(
                    item.weak_budget_balance_rate for item in items
                ),
                minimum_strong_budget_balance_rate=(
                    min(strong_rates) if len(strong_rates) == len(items) else None
                ),
                weak_budget_balance_profile_pass_count=sum(
                    item.weak_budget_balance_rate == 1.0 for item in items
                ),
                strong_budget_balance_profile_pass_count=sum(
                    item.strong_budget_balance_rate == 1.0 for item in items
                ),
            )
        )
    return tuple(summaries)


def summarize_headline_regret(
    cells: Iterable[AggregateTypeCellSummary],
    *,
    tolerance: float = 1e-12,
) -> tuple[AggregateTypeRegretSummary, ...]:
    """Compute minimax expected-GFT regret within the headline evidence tier."""

    headline = tuple(
        cell for cell in cells if cell.comparison_group == "headline_reference"
    )
    profiles = sorted({cell.case_id for cell in headline})
    methods = sorted({cell.method_id for cell in headline})
    lookup = {(cell.method_id, cell.case_id): cell.expected_gft for cell in headline}
    if not profiles or set(lookup) != {
        (method_id, profile_id)
        for method_id in methods
        for profile_id in profiles
    }:
        raise ValueError("headline regret requires a complete method/profile panel")
    best_by_profile = {
        profile_id: max(lookup[(method_id, profile_id)] for method_id in methods)
        for profile_id in profiles
    }
    provisional: list[tuple[str, float, float, str]] = []
    for method_id in methods:
        regrets = [
            (
                best_by_profile[profile_id] - lookup[(method_id, profile_id)],
                profile_id,
            )
            for profile_id in profiles
        ]
        worst_regret, worst_profile = max(regrets)
        provisional.append(
            (
                method_id,
                fmean(regret for regret, _ in regrets),
                worst_regret,
                worst_profile,
            )
        )
    minimax = min(row[2] for row in provisional)
    return tuple(
        AggregateTypeRegretSummary(
            method_id=method_id,
            profile_count=len(profiles),
            macro_profile_regret=macro_regret,
            worst_profile_regret=worst_regret,
            worst_profile_id=worst_profile,
            minimax_selected=abs(worst_regret - minimax) <= tolerance,
        )
        for method_id, macro_regret, worst_regret, worst_profile in provisional
    )


def summarize_point_selection_transfer(
    cells: Iterable[AggregateTypeCellSummary],
    *,
    tolerance: float = 1e-12,
) -> tuple[AggregateTypeSelectionTransferSummary, ...]:
    """Measure regret from selecting a mechanism on only one type profile.

    When a selection profile has tied winners, optimistic transfer assumes the
    best tied method is chosen for each target; pessimistic transfer assumes the
    worst tied method.  Neither quantity treats the nine profiles as sampled
    observations.
    """

    headline = tuple(
        cell for cell in cells if cell.comparison_group == "headline_reference"
    )
    profiles = sorted({cell.case_id for cell in headline})
    methods = sorted({cell.method_id for cell in headline})
    lookup = {(cell.method_id, cell.case_id): cell.expected_gft for cell in headline}
    expected_panel = {
        (method_id, profile_id)
        for method_id in methods
        for profile_id in profiles
    }
    if not profiles or set(lookup) != expected_panel:
        raise ValueError("point-selection transfer requires a complete headline panel")

    best_by_profile = {
        profile_id: max(lookup[(method_id, profile_id)] for method_id in methods)
        for profile_id in profiles
    }
    method_worst_regret = {
        method_id: max(
            best_by_profile[profile_id] - lookup[(method_id, profile_id)]
            for profile_id in profiles
        )
        for method_id in methods
    }
    minimax_regret = min(method_worst_regret.values())

    summaries: list[AggregateTypeSelectionTransferSummary] = []
    for selection_profile in profiles:
        selection_best = best_by_profile[selection_profile]
        selected = sorted(
            method_id
            for method_id in methods
            if abs(lookup[(method_id, selection_profile)] - selection_best) <= tolerance
        )
        optimistic: list[tuple[float, str]] = []
        pessimistic: list[tuple[float, str]] = []
        for target_profile in profiles:
            selected_values = [
                lookup[(method_id, target_profile)] for method_id in selected
            ]
            optimistic.append(
                (best_by_profile[target_profile] - max(selected_values), target_profile)
            )
            pessimistic.append(
                (best_by_profile[target_profile] - min(selected_values), target_profile)
            )
        worst_optimistic, worst_optimistic_target = max(optimistic)
        worst_pessimistic, worst_pessimistic_target = max(pessimistic)
        summaries.append(
            AggregateTypeSelectionTransferSummary(
                selection_profile_id=selection_profile,
                selected_method_ids=";".join(selected),
                selected_method_count=len(selected),
                target_profile_count=len(profiles),
                mean_optimistic_transfer_regret=fmean(
                    regret for regret, _ in optimistic
                ),
                worst_optimistic_transfer_regret=worst_optimistic,
                worst_optimistic_target_profile_id=worst_optimistic_target,
                mean_pessimistic_transfer_regret=fmean(
                    regret for regret, _ in pessimistic
                ),
                worst_pessimistic_transfer_regret=worst_pessimistic,
                worst_pessimistic_target_profile_id=worst_pessimistic_target,
                optimistically_minimax_robust=(
                    worst_optimistic <= minimax_regret + tolerance
                ),
                pessimistically_minimax_robust=(
                    worst_pessimistic <= minimax_regret + tolerance
                ),
            )
        )
    return tuple(summaries)


def summarize_selection_views(
    cells: Iterable[AggregateTypeCellSummary],
    catalog: Mapping[str, Any],
    *,
    tolerance: float = 1e-12,
) -> tuple[
    tuple[AggregateTypeSelectionViewProfile, ...],
    tuple[AggregateTypeSelectionViewSummary, ...],
]:
    """Evaluate declarative constraint/fidelity views without a composite score."""

    materialized = tuple(cells)
    if not materialized:
        raise ValueError("selection views require at least one profile cell")
    profiles = sorted({cell.case_id for cell in materialized})
    methods = sorted({cell.method_id for cell in materialized})
    lookup = {(cell.method_id, cell.case_id): cell for cell in materialized}
    if set(lookup) != {
        (method_id, profile_id)
        for method_id in methods
        for profile_id in profiles
    }:
        raise ValueError("selection views require a complete method/profile panel")

    raw_views = catalog.get("selection_views")
    if not isinstance(raw_views, list) or not raw_views:
        raise ValueError("selection_views must be a non-empty list")
    allowed_constraints = {
        "individual_rationality",
        "weak_budget_balance",
        "strong_budget_balance",
    }
    allowed_groups = {cell.comparison_group for cell in materialized}
    allowed_provenance = {cell.provenance_kind for cell in materialized}
    unrestricted_best = {
        profile_id: max(
            lookup[(method_id, profile_id)].expected_gft for method_id in methods
        )
        for profile_id in profiles
    }

    profile_rows: list[AggregateTypeSelectionViewProfile] = []
    seen_views: set[str] = set()
    for index, raw in enumerate(raw_views):
        view = _mapping(raw, f"selection_views[{index}]")
        view_id = str(view.get("view_id", "")).strip()
        label = str(view.get("label", "")).strip()
        if not view_id or view_id in seen_views or not label:
            raise ValueError("selection view IDs and labels must be non-empty and unique")
        seen_views.add(view_id)
        groups = {str(item) for item in view.get("comparison_groups", [])}
        provenance = {str(item) for item in view.get("provenance_kinds", [])}
        constraints = tuple(
            str(item) for item in view.get("required_empirical_constraints", [])
        )
        if not groups or groups - allowed_groups:
            raise ValueError(f"invalid comparison_groups for selection view {view_id}")
        if not provenance or provenance - allowed_provenance:
            raise ValueError(f"invalid provenance_kinds for selection view {view_id}")
        if set(constraints) - allowed_constraints:
            raise ValueError(f"invalid empirical constraint for selection view {view_id}")

        for profile_id in profiles:
            eligible: list[AggregateTypeCellSummary] = []
            for method_id in methods:
                cell = lookup[(method_id, profile_id)]
                if (
                    cell.comparison_group not in groups
                    or cell.provenance_kind not in provenance
                ):
                    continue
                rates = {
                    "individual_rationality": cell.individual_rationality_rate,
                    "weak_budget_balance": cell.weak_budget_balance_rate,
                    "strong_budget_balance": cell.strong_budget_balance_rate,
                }
                if all(rates[name] == 1.0 for name in constraints):
                    eligible.append(cell)
            if not eligible:
                raise ValueError(f"selection view has no eligible method:{view_id}:{profile_id}")
            best = max(cell.expected_gft for cell in eligible)
            winners = sorted(
                cell.method_id
                for cell in eligible
                if abs(cell.expected_gft - best) <= tolerance
            )
            eligible_ids = sorted(cell.method_id for cell in eligible)
            profile_rows.append(
                AggregateTypeSelectionViewProfile(
                    view_id=view_id,
                    view_label=label,
                    profile_id=profile_id,
                    eligible_method_ids=";".join(eligible_ids),
                    eligible_method_count=len(eligible_ids),
                    winner_ids=";".join(winners),
                    winner_count=len(winners),
                    best_expected_gft=best,
                    unrestricted_best_expected_gft=unrestricted_best[profile_id],
                    shortfall_vs_unrestricted=unrestricted_best[profile_id] - best,
                )
            )

    summaries: list[AggregateTypeSelectionViewSummary] = []
    for view_id in seen_views:
        items = [row for row in profile_rows if row.view_id == view_id]
        eligible_sets = [set(row.eligible_method_ids.split(";")) for row in items]
        winner_sets = [set(row.winner_ids.split(";")) for row in items]
        eligible_union = set.union(*eligible_sets)
        eligible_intersection = set.intersection(*eligible_sets)
        winner_union = set.union(*winner_sets)
        winner_intersection = set.intersection(*winner_sets)
        worst = max(items, key=lambda row: (row.shortfall_vs_unrestricted, row.profile_id))
        summaries.append(
            AggregateTypeSelectionViewSummary(
                view_id=view_id,
                view_label=items[0].view_label,
                profile_count=len(items),
                eligible_method_count=len(eligible_intersection),
                eligible_method_union_ids=";".join(sorted(eligible_union)),
                eligible_method_intersection_ids=";".join(
                    sorted(eligible_intersection)
                ),
                winner_union_ids=";".join(sorted(winner_union)),
                winner_intersection_ids=";".join(sorted(winner_intersection)),
                macro_best_expected_gft=fmean(row.best_expected_gft for row in items),
                worst_profile_best_expected_gft=min(
                    row.best_expected_gft for row in items
                ),
                max_shortfall_vs_unrestricted=worst.shortfall_vs_unrestricted,
                worst_profile_id=worst.profile_id,
            )
        )
    declared_order = [str(_mapping(row, "selection_view")["view_id"]) for row in raw_views]
    order = {view_id: index for index, view_id in enumerate(declared_order)}
    return (
        tuple(sorted(profile_rows, key=lambda row: (order[row.view_id], row.profile_id))),
        tuple(sorted(summaries, key=lambda row: order[row.view_id])),
    )


def summarize_joint_admissibility(
    cells: Iterable[AggregateTypeCellSummary],
    finite_audit: Mapping[str, Any],
) -> tuple[AggregateTypeJointAdmissibility, ...]:
    """Join profile constraints to the separate finite-deviation evidence layer."""

    headline = tuple(
        cell for cell in cells if cell.comparison_group == "headline_reference"
    )
    by_method: dict[str, list[AggregateTypeCellSummary]] = defaultdict(list)
    for cell in headline:
        by_method[cell.method_id].append(cell)
    if set(by_method) != set(HEADLINE_METHOD_IDS):
        raise ValueError("joint admissibility requires every headline method")
    profile_ids = {cell.case_id for cell in headline}
    if any({cell.case_id for cell in items} != profile_ids for items in by_method.values()):
        raise ValueError("joint admissibility requires a complete headline panel")

    raw_methods = finite_audit.get("methods")
    if not isinstance(raw_methods, list):
        raise ValueError("finite audit methods must be a list")
    finite_by_method: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_methods):
        row = _mapping(raw, f"finite_audit.methods[{index}]")
        method_id = str(row.get("method_id", "")).strip()
        if not method_id or method_id in finite_by_method:
            raise ValueError("finite audit method IDs must be non-empty and unique")
        finite_by_method[method_id] = row

    results: list[AggregateTypeJointAdmissibility] = []
    for method_id in HEADLINE_METHOD_IDS:
        items = by_method[method_id]
        provenance = {item.provenance_kind for item in items}
        if len(provenance) != 1:
            raise ValueError(f"inconsistent provenance for {method_id}")
        provenance_kind = next(iter(provenance))
        paper_exact = provenance_kind == "paper_exact"
        ir_all = all(item.individual_rationality_rate == 1.0 for item in items)
        wbb_all = all(item.weak_budget_balance_rate == 1.0 for item in items)
        sbb_applicable = all(
            item.strong_budget_balance_rate is not None for item in items
        )
        sbb_all = sbb_applicable and all(
            item.strong_budget_balance_rate == 1.0 for item in items
        )
        finite = finite_by_method.get(method_id)
        conclusion = str(finite.get("conclusion", "")) if finite else "missing"
        estimand = str(finite.get("estimand", "")) if finite else "missing"
        finite_no_counterexample = conclusion.startswith("no_counterexample_")
        reasons: list[str] = []
        if not paper_exact:
            reasons.append("source_fidelity")
        if not ir_all:
            reasons.append("individual_rationality")
        if not wbb_all:
            reasons.append("weak_budget_balance")
        if not sbb_applicable:
            reasons.append("strong_budget_balance_unavailable")
        elif not sbb_all:
            reasons.append("strong_budget_balance")
        if finite is None:
            reasons.append("finite_evidence_missing")
        elif not finite_no_counterexample:
            reasons.append("finite_counterexample")
        results.append(
            AggregateTypeJointAdmissibility(
                method_id=method_id,
                provenance_kind=provenance_kind,
                profile_count=len(items),
                paper_exact=paper_exact,
                individual_rationality_all_profiles=ir_all,
                weak_budget_balance_all_profiles=wbb_all,
                strong_budget_balance_applicable_all_profiles=sbb_applicable,
                strong_budget_balance_all_profiles=sbb_all,
                finite_audit_conclusion=conclusion,
                finite_audit_estimand=estimand,
                finite_report_domain_complete=(
                    bool(finite.get("report_domain_complete")) if finite else False
                ),
                finite_type_domain_complete=(
                    bool(finite.get("type_domain_complete")) if finite else False
                ),
                finite_random_support_complete=(
                    bool(finite.get("random_support_complete")) if finite else False
                ),
                finite_no_counterexample_on_declared_estimand=finite_no_counterexample,
                joint_admissible=not reasons,
                exclusion_reasons=";".join(reasons),
            )
        )
    return tuple(results)


def summarize_admissibility_relaxations(
    cells: Iterable[AggregateTypeCellSummary],
    joint_admissibility: Iterable[AggregateTypeJointAdmissibility],
) -> tuple[AggregateTypeAdmissibilityRelaxation, ...]:
    """Locate which single joint-admission requirements change the candidate set."""

    materialized = tuple(cells)
    joint = tuple(joint_admissibility)
    if {row.method_id for row in joint} != set(HEADLINE_METHOD_IDS):
        raise ValueError("relaxation frontier requires every headline method")
    profile_ids = sorted({row.case_id for row in materialized})
    if not profile_ids:
        raise ValueError("relaxation frontier requires at least one profile")
    by_method_profile = {
        (row.method_id, row.case_id): row.expected_gft for row in materialized
    }
    if any(
        (method_id, profile_id) not in by_method_profile
        for method_id in HEADLINE_METHOD_IDS
        for profile_id in profile_ids
    ):
        raise ValueError("relaxation frontier requires a complete headline panel")

    unrestricted_best = {
        profile_id: max(
            row.expected_gft for row in materialized if row.case_id == profile_id
        )
        for profile_id in profile_ids
    }
    headline_best = {
        profile_id: max(
            by_method_profile[(method_id, profile_id)]
            for method_id in HEADLINE_METHOD_IDS
        )
        for profile_id in profile_ids
    }
    requirements = (
        ("source_fidelity", lambda row: row.paper_exact),
        (
            "individual_rationality",
            lambda row: row.individual_rationality_all_profiles,
        ),
        (
            "weak_budget_balance",
            lambda row: row.weak_budget_balance_all_profiles,
        ),
        (
            "strong_budget_balance",
            lambda row: row.strong_budget_balance_applicable_all_profiles
            and row.strong_budget_balance_all_profiles,
        ),
        (
            "finite_no_counterexample",
            lambda row: row.finite_no_counterexample_on_declared_estimand,
        ),
    )
    views: tuple[tuple[str, str | None], ...] = (
        ("full_gate", None),
        *((f"drop_{name}", name) for name, _ in requirements),
    )
    results: list[AggregateTypeAdmissibilityRelaxation] = []
    for relaxation_id, relaxed in views:
        admitted = sorted(
            row.method_id
            for row in joint
            if all(
                name == relaxed or predicate(row)
                for name, predicate in requirements
            )
        )
        if not admitted:
            results.append(
                AggregateTypeAdmissibilityRelaxation(
                    relaxation_id=relaxation_id,
                    relaxed_requirement=relaxed or "none",
                    admitted_method_count=0,
                    admitted_method_ids="",
                    frontier_status=(
                        "empty_full_gate" if relaxed is None else "inactive_relaxation"
                    ),
                    profile_count=len(profile_ids),
                    macro_best_expected_gft=None,
                    worst_profile_best_expected_gft=None,
                    max_shortfall_vs_headline_best=None,
                    worst_headline_shortfall_profile_id="",
                    max_shortfall_vs_unrestricted=None,
                    worst_unrestricted_shortfall_profile_id="",
                )
            )
            continue
        best_by_profile = {
            profile_id: max(
                by_method_profile[(method_id, profile_id)]
                for method_id in admitted
            )
            for profile_id in profile_ids
        }
        headline_shortfall = {
            profile_id: headline_best[profile_id] - best_by_profile[profile_id]
            for profile_id in profile_ids
        }
        unrestricted_shortfall = {
            profile_id: unrestricted_best[profile_id] - best_by_profile[profile_id]
            for profile_id in profile_ids
        }
        worst_headline = max(
            profile_ids, key=lambda profile_id: (headline_shortfall[profile_id], profile_id)
        )
        worst_unrestricted = max(
            profile_ids,
            key=lambda profile_id: (unrestricted_shortfall[profile_id], profile_id),
        )
        results.append(
            AggregateTypeAdmissibilityRelaxation(
                relaxation_id=relaxation_id,
                relaxed_requirement=relaxed or "none",
                admitted_method_count=len(admitted),
                admitted_method_ids=";".join(admitted),
                frontier_status="active_relaxation" if relaxed else "admitted_full_gate",
                profile_count=len(profile_ids),
                macro_best_expected_gft=fmean(best_by_profile.values()),
                worst_profile_best_expected_gft=min(best_by_profile.values()),
                max_shortfall_vs_headline_best=headline_shortfall[worst_headline],
                worst_headline_shortfall_profile_id=worst_headline,
                max_shortfall_vs_unrestricted=unrestricted_shortfall[
                    worst_unrestricted
                ],
                worst_unrestricted_shortfall_profile_id=worst_unrestricted,
            )
        )
    return tuple(results)


def find_rank_reversals(
    cells: Iterable[AggregateTypeCellSummary],
    *,
    tolerance: float = 1e-12,
    comparison_group: str | None = None,
) -> tuple[AggregateTypeRankReversal, ...]:
    """Find method pairs whose expected-GFT order changes across profiles."""

    materialized = tuple(
        cell
        for cell in cells
        if comparison_group is None or cell.comparison_group == comparison_group
    )
    if not materialized:
        raise ValueError("rank-reversal analysis requires at least one cell")
    methods = sorted({cell.method_id for cell in materialized})
    profiles = sorted({cell.case_id for cell in materialized})
    lookup = {(cell.method_id, cell.case_id): cell.expected_gft for cell in materialized}
    if set(lookup) != {(method, profile) for method in methods for profile in profiles}:
        raise ValueError("rank-reversal analysis requires a complete method/profile panel")
    reversals: list[AggregateTypeRankReversal] = []
    for index, method_a in enumerate(methods):
        for method_b in methods[index + 1 :]:
            differences = [
                (lookup[(method_a, profile)] - lookup[(method_b, profile)], profile)
                for profile in profiles
            ]
            minimum, minimum_profile = min(differences)
            maximum, maximum_profile = max(differences)
            if minimum < -tolerance and maximum > tolerance:
                reversals.append(
                    AggregateTypeRankReversal(
                        method_a=method_a,
                        method_b=method_b,
                        minimum_difference=minimum,
                        minimum_profile_id=minimum_profile,
                        maximum_difference=maximum,
                        maximum_profile_id=maximum_profile,
                    )
                )
    return tuple(reversals)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, object]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        for row in rows
    ).encode("utf-8")


def _csv_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    if not rows:
        raise ValueError("cannot render an empty CSV")
    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _findings(
    cells: Sequence[AggregateTypeCellSummary],
    methods: Sequence[AggregateTypeMethodSummary],
    headline_regret: Sequence[AggregateTypeRegretSummary],
    point_selection_transfer: Sequence[AggregateTypeSelectionTransferSummary],
    selection_views: Sequence[AggregateTypeSelectionViewSummary],
    joint_admissibility: Sequence[AggregateTypeJointAdmissibility],
    admissibility_relaxations: Sequence[AggregateTypeAdmissibilityRelaxation],
    headline_reversals: Sequence[AggregateTypeRankReversal],
    all_reversals: Sequence[AggregateTypeRankReversal],
) -> dict[str, object]:
    by_profile: dict[str, list[AggregateTypeCellSummary]] = defaultdict(list)
    for cell in cells:
        by_profile[cell.case_id].append(cell)
    winners: list[dict[str, object]] = []
    qualified_winners: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    qualified_counts: Counter[str] = Counter()
    for profile_id, items in sorted(by_profile.items()):
        best = max(item.expected_gft for item in items)
        winner_ids = sorted(
            item.method_id for item in items if abs(item.expected_gft - best) <= 1e-12
        )
        counts.update(winner_ids)
        winners.append(
            {
                "profile_id": profile_id,
                "expected_gft": best,
                "winner_ids": winner_ids,
            }
        )
        qualified_items = [
            item
            for item in items
            if item.individual_rationality_rate == 1.0
            and item.weak_budget_balance_rate == 1.0
        ]
        qualified_best = max(item.expected_gft for item in qualified_items)
        qualified_ids = sorted(
            item.method_id
            for item in qualified_items
            if abs(item.expected_gft - qualified_best) <= 1e-12
        )
        qualified_counts.update(qualified_ids)
        qualified_winners.append(
            {
                "profile_id": profile_id,
                "expected_gft": qualified_best,
                "winner_ids": qualified_ids,
            }
        )
    minimax_regret = min(row.worst_profile_regret for row in headline_regret)
    worst_point_selection_regret = max(
        row.worst_pessimistic_transfer_regret for row in point_selection_transfer
    )
    strict_view = next(
        row for row in selection_views if row.view_id == "paper_exact_ir_wbb_sbb"
    )
    joint_admissible_ids = [
        row.method_id for row in joint_admissibility if row.joint_admissible
    ]
    joint_near_miss_ids = sorted(
        row.method_id
        for row in joint_admissibility
        if len([reason for reason in row.exclusion_reasons.split(";") if reason]) == 1
    )
    active_relaxations = sorted(
        row.relaxed_requirement
        for row in admissibility_relaxations
        if row.frontier_status == "active_relaxation"
    )
    relaxation_by_requirement = {
        row.relaxed_requirement: row for row in admissibility_relaxations
    }
    sbb_relaxation = relaxation_by_requirement["strong_budget_balance"]
    finite_relaxation = relaxation_by_requirement["finite_no_counterexample"]
    relaxation_regret_inflation = (
        finite_relaxation.max_shortfall_vs_headline_best
        / sbb_relaxation.max_shortfall_vs_headline_best
        if finite_relaxation.max_shortfall_vs_headline_best is not None
        and sbb_relaxation.max_shortfall_vs_headline_best not in (None, 0.0)
        else None
    )
    return {
        "schema_version": "1.0",
        "study_id": "cnil-aggregate-type-envelope-v1",
        "evidence_scope": EVIDENCE_SCOPE,
        "profile_count": len(by_profile),
        "method_count": len(methods),
        "headline_method_count": sum(
            row.comparison_group == "headline_reference" for row in methods
        ),
        "raw_gft_profile_winners": winners,
        "winner_profile_counts_including_ties": dict(sorted(counts.items())),
        "ir_wbb_qualified_gft_profile_winners": qualified_winners,
        "ir_wbb_qualified_winner_profile_counts_including_ties": dict(
            sorted(qualified_counts.items())
        ),
        "qualification_boundary": (
            "IR and WBB only; source fidelity and strategic guarantees remain separate"
        ),
        "headline_minimax_regret_method_ids": [
            row.method_id for row in headline_regret if row.minimax_selected
        ],
        "headline_minimax_regret_method_count": sum(
            row.minimax_selected for row in headline_regret
        ),
        "headline_minimax_regret": minimax_regret,
        "headline_regret_scope": (
            "profile-level expected GFT relative to the best headline reference"
        ),
        "point_selection_worst_regret": worst_point_selection_regret,
        "point_selection_worst_regret_inflation": (
            worst_point_selection_regret / minimax_regret
            if minimax_regret > 0
            else None
        ),
        "optimistically_fragile_selection_profile_count": sum(
            not row.optimistically_minimax_robust for row in point_selection_transfer
        ),
        "pessimistically_fragile_selection_profile_count": sum(
            not row.pessimistically_minimax_robust for row in point_selection_transfer
        ),
        "point_selection_scope": (
            "select headline expected-GFT winner(s) on one profile and transfer "
            "that selection to every other aggregate-compatible profile"
        ),
        "strict_selection_view_id": strict_view.view_id,
        "strict_selection_eligible_method_count": strict_view.eligible_method_count,
        "strict_selection_winner_union_ids": strict_view.winner_union_ids.split(";"),
        "strict_selection_winner_intersection_ids": (
            strict_view.winner_intersection_ids.split(";")
            if strict_view.winner_intersection_ids
            else []
        ),
        "strict_selection_max_shortfall_vs_unrestricted": (
            strict_view.max_shortfall_vs_unrestricted
        ),
        "strict_selection_interpretation": (
            "Observed IR/WBB/SBB and paper-exact provenance produce a stable "
            "winner on this type grid, but do not establish incentive compatibility; "
            "the finite-domain audit remains a separate evidence layer."
        ),
        "joint_admissible_method_count": len(joint_admissible_ids),
        "joint_admissible_method_ids": joint_admissible_ids,
        "joint_near_miss_method_ids": joint_near_miss_ids,
        "joint_admissibility_scope": (
            "paper-exact headline provenance AND observed IR/WBB/SBB on every "
            "aggregate-compatible profile AND no counterexample on the separately "
            "declared finite report/type/seed estimand"
        ),
        "joint_admissibility_boundary": (
            "passing would remain finite empirical evidence, not a theorem; "
            "failure identifies which evidence dimension blocks admission"
        ),
        "admissibility_active_relaxations": active_relaxations,
        "admissibility_relaxation_regret_inflation": relaxation_regret_inflation,
        "admissibility_relaxation_scope": (
            "leave exactly one joint requirement out while retaining every other "
            "requirement; compare admitted mechanisms against the per-profile "
            "headline and unrestricted best"
        ),
        "rank_reversal_count": len(headline_reversals),
        "rank_reversal_pairs": [
            [row.method_a, row.method_b] for row in headline_reversals
        ],
        "all_method_rank_reversal_count": len(all_reversals),
        "all_method_rank_reversal_pairs": [
            [row.method_a, row.method_b] for row in all_reversals
        ],
        "interpretation": {
            "primary": (
                "Mechanism choice changes across aggregate-anchor-compatible "
                "within-interval placements, so point-imputing grouped prices can "
                "create a spurious stable ranking."
            ),
            "not_identified": [
                "respondent-level types",
                "population welfare",
                "sharp partial-identification bounds",
                "universal mechanism winner",
            ],
        },
    }


def _report(
    run_count: int,
    cells: Sequence[AggregateTypeCellSummary],
    methods: Sequence[AggregateTypeMethodSummary],
    headline_regret: Sequence[AggregateTypeRegretSummary],
    point_selection_transfer: Sequence[AggregateTypeSelectionTransferSummary],
    selection_views: Sequence[AggregateTypeSelectionViewSummary],
    joint_admissibility: Sequence[AggregateTypeJointAdmissibility],
    admissibility_relaxations: Sequence[AggregateTypeAdmissibilityRelaxation],
    headline_reversals: Sequence[AggregateTypeRankReversal],
    all_reversals: Sequence[AggregateTypeRankReversal],
) -> str:
    lines = [
        "# Aggregate type-envelope study",
        "",
        f"This study evaluates {len(methods)} double-auction comparators, including ",
        "five headline reference mechanisms, on nine ",
        "model-generated profiles compatible with the published CNIL aggregate ",
        "supply/demand anchors. The profiles are not respondent microdata and the ",
        "reported seller amounts are stated, not incentive-compatible, types.",
        "",
        f"- runs: {run_count}",
        f"- profile-method cells: {len(cells)}",
        f"- headline rank-reversing method pairs: {len(headline_reversals)}",
        f"- all-method rank-reversing pairs: {len(all_reversals)}",
        "",
        "## Cross-profile robustness",
        "",
        "| Method | Group | Macro expected GFT | Worst | Best | Range | Min WBB | Min SBB |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in methods:
        lines.append(
            f"| {row.method_id} | {row.comparison_group} | "
            f"{row.macro_expected_gft:.6f} | "
            f"{row.worst_profile_gft:.6f} | {row.best_profile_gft:.6f} | "
            f"{row.sensitivity_range:.6f} | "
            f"{row.minimum_weak_budget_balance_rate:.3f} | "
            f"{row.minimum_strong_budget_balance_rate if row.minimum_strong_budget_balance_rate is not None else 'N/A'} |"
        )
    lines.extend(["", "## Headline-reference rank reversals", ""])
    if not headline_reversals:
        lines.append("No reversal exceeded the declared numerical tolerance.")
    for row in headline_reversals:
        lines.append(
            f"- `{row.method_a}` minus `{row.method_b}` ranges from "
            f"{row.minimum_difference:.6f} in `{row.minimum_profile_id}` to "
            f"{row.maximum_difference:.6f} in `{row.maximum_profile_id}`."
        )
    selected = [row.method_id for row in headline_regret if row.minimax_selected]
    minimax = min(row.worst_profile_regret for row in headline_regret)
    lines.extend(
        [
            "",
            "## Headline minimax-regret set",
            "",
            f"- selected methods: {', '.join(f'`{item}`' for item in selected)}",
            f"- worst-case expected-GFT regret: {minimax:.6f}",
            "",
            "Regret is relative to the best headline reference within each profile; ",
            "it is not computed against pricing baselines or the VCG guardrail.",
        ]
    )
    lines.extend(
        [
            "",
            "## Joint claim-aligned admissibility",
            "",
            "| Method | Paper exact | IR all | WBB all | SBB all | Finite no-counterexample | Joint pass | Exclusion |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in joint_admissibility:
        lines.append(
            f"| {row.method_id} | {row.paper_exact} | "
            f"{row.individual_rationality_all_profiles} | "
            f"{row.weak_budget_balance_all_profiles} | "
            f"{row.strong_budget_balance_all_profiles} | "
            f"{row.finite_no_counterexample_on_declared_estimand} | "
            f"{row.joint_admissible} | {row.exclusion_reasons or 'none'} |"
        )
    passing = [row.method_id for row in joint_admissibility if row.joint_admissible]
    lines.extend(
        [
            "",
            f"Jointly admitted headline methods: {', '.join(passing) if passing else 'none'}.",
            "McAfee and Trade Reduction are blocked by SBB; SBBA is blocked by "
            "the retained finite counterexamples. This is an empirical gate over "
            "declared scopes, not a proof or theorem refutation.",
        ]
    )
    lines.extend(
        [
            "",
            "## Leave-one-requirement-out admission frontier",
            "",
            "| Relaxed requirement | Admitted methods | Worst shortfall vs headline best | Worst shortfall vs unrestricted |",
            "|---|---|---:|---:|",
        ]
    )
    for row in admissibility_relaxations:
        headline_gap = (
            f"{row.max_shortfall_vs_headline_best:.6f}"
            if row.max_shortfall_vs_headline_best is not None
            else "N/A"
        )
        unrestricted_gap = (
            f"{row.max_shortfall_vs_unrestricted:.6f}"
            if row.max_shortfall_vs_unrestricted is not None
            else "N/A"
        )
        lines.append(
            f"| {row.relaxed_requirement} | "
            f"{row.admitted_method_ids or 'none'} | {headline_gap} | "
            f"{unrestricted_gap} |"
        )
    lines.extend(
        [
            "",
            "Only SBB and the finite no-counterexample requirement are active "
            "single relaxations. Dropping SBB admits McAfee and Trade Reduction; "
            "dropping the finite gate admits SBBA. This diagnostic does not "
            "recommend relaxing either requirement.",
        ]
    )
    lines.extend(
        [
            "",
            "## Constraint and fidelity selection views",
            "",
            "| View | Eligible methods on every profile | Winner union | Stable winner intersection | Max GFT shortfall |",
            "|---|---:|---|---|---:|",
        ]
    )
    for row in selection_views:
        lines.append(
            f"| {row.view_id} | {row.eligible_method_count} | "
            f"{row.winner_union_ids or 'none'} | "
            f"{row.winner_intersection_ids or 'none'} | "
            f"{row.max_shortfall_vs_unrestricted:.6f} |"
        )
    lines.extend(
        [
            "",
            "In the strict paper-exact IR/WBB/SBB view, SBBA is the only winner "
            "present on every profile, while McAfee co-wins on some profiles. "
            "This table does not upgrade observed constraints to a strategic "
            "theorem; the separate finite-domain audit retains its counterexamples.",
        ]
    )
    minimax = min(row.worst_profile_regret for row in headline_regret)
    worst_transfer = max(
        row.worst_pessimistic_transfer_regret for row in point_selection_transfer
    )
    optimistic_fragile = sum(
        not row.optimistically_minimax_robust for row in point_selection_transfer
    )
    pessimistic_fragile = sum(
        not row.pessimistically_minimax_robust for row in point_selection_transfer
    )
    lines.extend(
        [
            "",
            "## Point-profile selection transfer",
            "",
            f"Selecting headline winner(s) on one imputed profile is non-minimax "
            f"for {optimistic_fragile}/9 profiles even under optimistic tie-breaking "
            f"and {pessimistic_fragile}/9 under pessimistic tie-breaking. The worst "
            f"transferred regret is {worst_transfer:.6f}, or "
            f"{worst_transfer / minimax:.3f} times the minimax regret.",
            "",
            "This is a decision-transfer sensitivity result, not a population "
            "probability or a claim that the nine profiles are equally likely.",
        ]
    )
    lines.extend(
        [
            "",
            "The separate all-method reversal table includes pricing baselines, a ",
            "canonical guardrail, and a diagnostic random-sampling comparator. It ",
            "must not be interpreted as one source-fidelity tier.",
        ]
    )
    lines.extend(
        [
            "",
            "These are sensitivity diagnostics, not confidence intervals or a "
            "population-level dominance result.",
            "",
        ]
    )
    return "\n".join(lines)


def build_aggregate_type_artifacts(
    output: str | Path = DEFAULT_OUTPUT,
    catalog_path: str | Path = DEFAULT_CATALOG,
    *,
    seeds: Sequence[int] = tuple(range(32)),
    finite_audit_path: str | Path = DEFAULT_FINITE_AUDIT,
) -> dict[str, object]:
    """Build a deterministic, self-auditing aggregate-envelope result bundle."""

    output_path = Path(output)
    source_path = Path(catalog_path)
    finite_path = Path(finite_audit_path)
    catalog = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    finite_audit = json.loads(finite_path.read_text(encoding="utf-8"))
    rows = run_aggregate_type_envelope(catalog, seeds=seeds)
    cells = summarize_aggregate_type_cells(rows)
    methods = summarize_aggregate_type_methods(cells)
    headline_regret = summarize_headline_regret(cells)
    point_selection_transfer = summarize_point_selection_transfer(cells)
    selection_view_profiles, selection_views = summarize_selection_views(cells, catalog)
    joint_admissibility = summarize_joint_admissibility(cells, finite_audit)
    admissibility_relaxations = summarize_admissibility_relaxations(
        cells, joint_admissibility
    )
    all_reversals = find_rank_reversals(cells)
    headline_reversals = find_rank_reversals(
        cells, comparison_group="headline_reference"
    )
    payloads = {
        "raw_runs.jsonl": _jsonl_bytes(row.to_dict() for row in rows),
        "profile_method_summary.csv": _csv_bytes(
            [row.to_dict() for row in cells]
        ),
        "method_robustness_summary.csv": _csv_bytes(
            [row.to_dict() for row in methods]
        ),
        "headline_regret_summary.csv": _csv_bytes(
            [row.to_dict() for row in headline_regret]
        ),
        "point_selection_transfer.csv": _csv_bytes(
            [row.to_dict() for row in point_selection_transfer]
        ),
        "selection_view_profile.csv": _csv_bytes(
            [row.to_dict() for row in selection_view_profiles]
        ),
        "selection_view_summary.csv": _csv_bytes(
            [row.to_dict() for row in selection_views]
        ),
        "joint_admissibility.csv": _csv_bytes(
            [row.to_dict() for row in joint_admissibility]
        ),
        "admissibility_relaxation_frontier.csv": _csv_bytes(
            [row.to_dict() for row in admissibility_relaxations]
        ),
        "rank_reversals.csv": _csv_bytes(
            [row.to_dict() for row in headline_reversals]
            or [{
                "method_a": "",
                "method_b": "",
                "minimum_difference": "",
                "minimum_profile_id": "",
                "maximum_difference": "",
                "maximum_profile_id": "",
                "comparison_metric": "",
            }]
        ),
        "all_method_rank_reversals.csv": _csv_bytes(
            [row.to_dict() for row in all_reversals]
            or [{
                "method_a": "",
                "method_b": "",
                "minimum_difference": "",
                "minimum_profile_id": "",
                "maximum_difference": "",
                "maximum_profile_id": "",
                "comparison_metric": "",
            }]
        ),
        "findings.json": _json_bytes(
            _findings(
                cells,
                methods,
                headline_regret,
                point_selection_transfer,
                selection_views,
                joint_admissibility,
                admissibility_relaxations,
                headline_reversals,
                all_reversals,
            )
        ),
        "report.md": _report(
            len(rows),
            cells,
            methods,
            headline_regret,
            point_selection_transfer,
            selection_views,
            joint_admissibility,
            admissibility_relaxations,
            headline_reversals,
            all_reversals,
        ).encode("utf-8"),
    }
    for name, payload in payloads.items():
        _atomic_write(output_path / name, payload)
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "artifact_kind": "aggregate_type_envelope_study",
        "study_id": str(catalog["study_id"]),
        "setting_id": str(catalog["setting_id"]),
        "evidence_scope": EVIDENCE_SCOPE,
        "valid": True,
        "errors": [],
        "run_count": len(rows),
        "profile_count": len({row.case_id for row in rows}),
        "method_count": len({row.method_id for row in rows}),
        "headline_method_count": sum(
            row.comparison_group == "headline_reference" for row in methods
        ),
        "cell_count": len(cells),
        "rank_reversal_count": len(headline_reversals),
        "all_method_rank_reversal_count": len(all_reversals),
        "seeds": list(seeds),
        "source_catalog": "benchmark/catalog/aggregate_type_envelope.yaml",
        "source_catalog_sha256": _sha256(source_path),
        "finite_incentive_audit": (
            "benchmark/outputs/kdd_finite_incentives/audit_results.json"
        ),
        "finite_incentive_audit_sha256": _sha256(finite_path),
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            for name, payload in sorted(payloads.items())
        },
    }
    _atomic_write(output_path / "manifest.json", _json_bytes(manifest))
    return manifest


def verify_aggregate_type_artifacts(manifest_path: str | Path) -> dict[str, object]:
    """Verify every declared artifact byte and the basic bundle dimensions."""

    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("artifact_kind") != "aggregate_type_envelope_study":
        errors.append("artifact_kind_mismatch")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != set(OUTPUT_NAMES):
        errors.append("file_set_mismatch")
        files = {}
    for name, raw in files.items():
        binding = _mapping(raw, f"files.{name}")
        candidate = path.parent / name
        if not candidate.is_file():
            errors.append(f"missing_file:{name}")
            continue
        if _sha256(candidate) != binding.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
        if candidate.stat().st_size != binding.get("bytes"):
            errors.append(f"size_mismatch:{name}")
    raw_path = path.parent / "raw_runs.jsonl"
    if raw_path.is_file():
        observed_runs = sum(1 for line in raw_path.read_text().splitlines() if line)
        if observed_runs != manifest.get("run_count"):
            errors.append("run_count_mismatch")
    result = dict(manifest)
    result["valid"] = not errors
    result["errors"] = errors
    return result


__all__ = [
    "AggregateTypeAdmissibilityRelaxation",
    "AggregateTypeCellSummary",
    "AggregateTypeJointAdmissibility",
    "AggregateTypeMethodSummary",
    "AggregateTypeRankReversal",
    "AggregateTypeRun",
    "AggregateTypeSelectionTransferSummary",
    "AggregateTypeSelectionViewProfile",
    "AggregateTypeSelectionViewSummary",
    "DEFAULT_CATALOG",
    "DEFAULT_FINITE_AUDIT",
    "DEFAULT_OUTPUT",
    "ENVELOPE_METHOD_IDS",
    "build_aggregate_type_artifacts",
    "build_aggregate_type_cases",
    "find_rank_reversals",
    "run_aggregate_type_envelope",
    "summarize_aggregate_type_cells",
    "summarize_aggregate_type_methods",
    "summarize_admissibility_relaxations",
    "summarize_headline_regret",
    "summarize_joint_admissibility",
    "summarize_point_selection_transfer",
    "summarize_selection_views",
    "verify_aggregate_type_artifacts",
]
