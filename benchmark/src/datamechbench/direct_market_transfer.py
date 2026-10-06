"""Exploratory procurement transfer audit on direct data-market listed asks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .heldout_sources import build_owner_dataset_from_arff
from .metrics import MetricValue, evaluate_procurement_metrics
from .models import MarketOutcome, ProcurementCase, ProcurementInput
from .registry import validate_output
from .runner import build_registry

DIRECT_MARKET_METHOD_IDS = (
    "generalized_proportional_share",
    "cgl_deterministic",
    "cgl_randomized",
    "jt_greedy_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
)
DIRECT_MARKET_SEEDS = (1701, 2903, 4703)
ORACLE_METHOD_ID = "budget_optimum"
OUTPUT_NAMES = (
    "raw_runs.jsonl",
    "cohort_method_summary.csv",
    "method_summary.csv",
    "transfer_contrasts.csv",
    "findings.json",
    "report.md",
)
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PACKAGE_ROOT / "outputs" / "kdd_direct_market_transfer"
DEFAULT_PROFILES = PACKAGE_ROOT / "data" / "market_calibration" / "dadada_price_profiles.json"
DEFAULT_CHILE_EVIDENCE = PACKAGE_ROOT / "evidence" / "kdd_heldout_confirmatory_v1.json"
OPENML_FILES = {
    44: ("spambase-44.arff", "class"),
    31: ("credit-g-31.arff", "class"),
    1461: ("bank-marketing-1461.arff", "Class"),
}


@dataclass(frozen=True)
class DirectMarketRun:
    run_id: str
    method_id: str
    method_role: str
    case_id: str
    seed: int
    status: str
    cohort_id: str
    platform: str
    price_mode: str
    source_listing_count: int
    dataset_id: str
    budget_ratio: float
    oracle_ratio: float | None
    realized_utility: float | None
    selected_count: int | None
    total_payment: float | None
    budget_violation: bool | None
    payment_complete: bool | None
    seller_ir_violation_count: int | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DirectMarketRun":
        return cls(**{field: value.get(field) for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class CohortMethodSummary:
    method_id: str
    cohort_id: str
    platform: str
    price_mode: str
    source_listing_count: int
    case_count: int
    run_count: int
    macro_oracle_ratio: float
    worst_case_oracle_ratio: float
    budget_feasible_rate: float
    payment_complete_rate: float
    seller_ir_auditable_rate: float
    seller_ir_pass_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DirectMethodSummary:
    method_id: str
    cohort_count: int
    case_count: int
    run_count: int
    macro_oracle_ratio: float
    worst_cohort_oracle_ratio: float
    best_cohort_oracle_ratio: float
    support_range: float
    worst_cohort_id: str
    budget_feasible_rate: float
    payment_complete_rate: float
    seller_ir_auditable_rate: float
    seller_ir_pass_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TransferContrast:
    contrast_id: str
    method_a: str
    method_b: str
    cohort_id: str
    platform: str
    price_mode: str
    direct_effect: float
    chile_effect_min: float
    chile_effect_max: float
    chile_sign_pattern: str
    outside_chile_range: bool
    comparison_scope: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _chile_contrast_scientific_sha256(evidence: Mapping[str, Any]) -> str:
    """Hash only the ChileCompra contrast fields consumed by this study."""

    contrasts = evidence["tracks"]["procurement"]["contrasts"]
    relevant: list[dict[str, Any]] = []
    required_ids = {"P-CGLR-vs-GPS", "P-JTDEOM-vs-GPS"}
    for raw in contrasts:
        contrast_id = str(raw["contrast_id"])
        if contrast_id not in required_ids:
            continue
        block_effects = {
            str(block_id): float(effect)
            for block_id, effect in raw["block_effects"].items()
        }
        if not block_effects:
            raise ValueError(f"empty ChileCompra block effects:{contrast_id}")
        relevant.append({
            "contrast_id": contrast_id,
            "method_a": str(raw["method_a"]),
            "method_b": str(raw["method_b"]),
            "block_effects": block_effects,
        })
    observed_ids = {item["contrast_id"] for item in relevant}
    if observed_ids != required_ids or len(relevant) != len(required_ids):
        raise ValueError(
            "missing or duplicate ChileCompra contrasts:"
            f"expected={sorted(required_ids)}:observed={sorted(observed_ids)}"
        )
    payload = _canonical_json(sorted(relevant, key=lambda item: item["contrast_id"]))
    return hashlib.sha256(payload).hexdigest()


def _exact_optimum(game: Any, costs: Mapping[str, Decimal], budget: Decimal) -> float:
    owners = tuple(game.owner_ids)
    best = float(game.utility_for_owners(()))
    for mask in range(1 << len(owners)):
        selected = tuple(
            owner for index, owner in enumerate(owners) if mask & (1 << index)
        )
        if sum((costs[owner] for owner in selected), Decimal("0")) <= budget:
            best = max(best, float(game.utility_for_owners(selected)))
    return best


def make_direct_market_procurement_cases(
    datasets: Mapping[str, Any],
    profiles: Mapping[str, Any],
    *,
    budget_ratios: Sequence[float] = (0.3, 0.5),
) -> tuple[ProcurementCase, ...]:
    """Cross anonymous listed-ask shapes with frozen owner utility games."""

    raw_cohorts = profiles.get("cohorts")
    if not isinstance(raw_cohorts, list) or not raw_cohorts:
        raise ValueError("direct-market profiles require non-empty cohorts")
    if not datasets:
        raise ValueError("direct-market transfer requires owner games")
    cases: list[ProcurementCase] = []
    for cohort in sorted(raw_cohorts, key=lambda item: str(item["cohort_id"])):
        cohort_id = str(cohort["cohort_id"])
        for dataset_id, game in sorted(datasets.items()):
            owners = tuple(game.owner_ids)
            raw_costs = cohort.get("reported_costs")
            if not isinstance(raw_costs, Mapping) or set(raw_costs) != set(owners):
                raise ValueError(f"reported costs do not match owner IDs:{cohort_id}")
            costs = {owner: Decimal(str(raw_costs[owner])) for owner in owners}
            if any(not cost.is_finite() or cost <= 0 for cost in costs.values()):
                raise ValueError(f"invalid reported cost:{cohort_id}")
            empty = float(game.utility_for_owners(()))
            seller_values = {
                owner: max(0.0, float(game.utility_for_owners((owner,))) - empty)
                for owner in owners
            }
            total_cost = sum(costs.values(), Decimal("0"))
            for ratio in budget_ratios:
                budget = total_cost * Decimal(str(ratio))
                optimum = _exact_optimum(game, costs, budget)
                largest_share = max(seller_values.values()) / optimum if optimum else 0.0
                case_id = f"PDM-{cohort_id}-{dataset_id}-b{int(100 * ratio)}"
                public = ProcurementInput(
                    seller_ids=owners,
                    reported_costs=dict(costs),
                    budget=budget,
                    utility=game.utility_for_owners,
                    seller_values=seller_values,
                    metadata={
                        "source_market": "DaDaDa",
                        "benchmark_setting": "P-DIRECT-LISTING-SUPPORT",
                        "price_mode": cohort["price_mode"],
                    },
                )
                cases.append(ProcurementCase(
                    case_id=case_id,
                    public=public,
                    true_costs=dict(costs),
                    case_type="real_owner_data",
                    metadata={
                        "benchmark_setting": "P-DIRECT-LISTING-SUPPORT",
                        "cohort": "exploratory",
                        "evidence_scope": "direct_data_market_listing_support",
                        "independent_block": cohort_id,
                        "cohort_id": cohort_id,
                        "platform": str(cohort["platform"]),
                        "price_mode": str(cohort["price_mode"]),
                        "source_listing_count": int(cohort["source_row_count"]),
                        "source_dataset": dataset_id,
                        "dataset_id": dataset_id,
                        "budget_ratio": float(ratio),
                        "largest_singleton_share": largest_share,
                        "exact_opt_utility": optimum,
                        "owner_dataset": game,
                        "pilot": False,
                        "assumptions": (
                            "observed_listing_price_shape",
                            "truthful_report_stress_proxy",
                            "listing_prices_are_not_reservation_costs",
                            "within_price_mode_normalization",
                            "single_parameter_sellers",
                        ),
                    },
                    attack_labels={owner: "truthful_stress_proxy" for owner in owners},
                ))
    return tuple(cases)


def _metric(metrics: Mapping[str, MetricValue], name: str) -> float | None:
    value = metrics[name]
    if not value.applicable:
        return None
    return float(value.value)


def _outcome_guardrails(
    case: ProcurementCase, outcome: MarketOutcome
) -> tuple[int, float, bool, bool, int | None]:
    selected = set(outcome.selected_ids)
    payments: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for payment in outcome.payments:
        payments[payment.payee_id] += payment.amount
    total = sum(payments.values(), Decimal("0"))
    complete = set(payments) == selected
    ir_violations = (
        sum(payments[seller] < case.true_costs[seller] for seller in selected)
        if complete
        else None
    )
    return (
        len(selected),
        float(total),
        total > case.public.budget,
        complete,
        ir_violations,
    )


def _run_key(method_id: str, case_id: str, seed: int) -> str:
    return f"direct-market::{method_id}::{case_id}::{seed}"


def run_direct_market_transfer(
    cases: Iterable[ProcurementCase],
    *,
    method_ids: Sequence[str] = DIRECT_MARKET_METHOD_IDS,
    seeds: Sequence[int] = DIRECT_MARKET_SEEDS,
) -> tuple[DirectMarketRun, ...]:
    """Execute the fixed direct-listing support transfer panel."""

    materialized = tuple(cases)
    if not materialized:
        raise ValueError("direct-market transfer requires cases")
    if tuple(method_ids) != DIRECT_MARKET_METHOD_IDS:
        raise ValueError("direct-market headline method panel is frozen")
    if tuple(seeds) != DIRECT_MARKET_SEEDS:
        raise ValueError("direct-market seed panel is frozen")
    registry = build_registry()
    rows: list[DirectMarketRun] = []
    for case in materialized:
        metadata = case.metadata
        oracle_method = registry.create(ORACLE_METHOD_ID)
        oracle = oracle_method.allocate(case.public, seed=seeds[0])
        validate_output(oracle_method.spec, case.public, oracle)
        oracle_utility = float(case.public.utility(oracle.selected_ids))
        rows.append(DirectMarketRun(
            run_id=_run_key(ORACLE_METHOD_ID, case.case_id, seeds[0]),
            method_id=ORACLE_METHOD_ID,
            method_role="oracle",
            case_id=case.case_id,
            seed=seeds[0],
            status="completed",
            cohort_id=str(metadata["cohort_id"]),
            platform=str(metadata["platform"]),
            price_mode=str(metadata["price_mode"]),
            source_listing_count=int(metadata["source_listing_count"]),
            dataset_id=str(metadata["dataset_id"]),
            budget_ratio=float(metadata["budget_ratio"]),
            oracle_ratio=1.0,
            realized_utility=oracle_utility,
            selected_count=len(oracle.selected_ids),
            total_payment=None,
            budget_violation=None,
            payment_complete=None,
            seller_ir_violation_count=None,
        ))
        for method_id in method_ids:
            method = registry.create(method_id)
            panel = tuple(seeds) if method.spec.stochastic else (seeds[0],)
            for seed in panel:
                common = {
                    "run_id": _run_key(method_id, case.case_id, seed),
                    "method_id": method_id,
                    "method_role": "headline",
                    "case_id": case.case_id,
                    "seed": int(seed),
                    "cohort_id": str(metadata["cohort_id"]),
                    "platform": str(metadata["platform"]),
                    "price_mode": str(metadata["price_mode"]),
                    "source_listing_count": int(metadata["source_listing_count"]),
                    "dataset_id": str(metadata["dataset_id"]),
                    "budget_ratio": float(metadata["budget_ratio"]),
                }
                try:
                    outcome = method.allocate(case.public, seed=int(seed))
                    validate_output(method.spec, case.public, outcome)
                    metrics = evaluate_procurement_metrics(
                        case,
                        outcome,
                        method.spec,
                        oracle,
                        method=None,
                        seed=int(seed),
                    )
                    selected, total, budget_violation, complete, ir = (
                        _outcome_guardrails(case, outcome)
                    )
                    rows.append(DirectMarketRun(
                        **common,
                        status="completed",
                        oracle_ratio=_metric(metrics, "oracle_ratio"),
                        realized_utility=_metric(metrics, "realized_utility"),
                        selected_count=selected,
                        total_payment=total,
                        budget_violation=budget_violation,
                        payment_complete=complete,
                        seller_ir_violation_count=ir,
                    ))
                except Exception as exc:  # retained as evidence by design
                    rows.append(DirectMarketRun(
                        **common,
                        status="failed",
                        oracle_ratio=None,
                        realized_utility=None,
                        selected_count=None,
                        total_payment=None,
                        budget_violation=None,
                        payment_complete=None,
                        seller_ir_violation_count=None,
                        error=f"{type(exc).__name__}: {exc}",
                    ))
    return tuple(sorted(rows, key=lambda row: (row.method_id, row.case_id, row.seed)))


def _expected_keys(case_ids: Iterable[str]) -> set[tuple[str, str, int]]:
    registry = build_registry()
    expected: set[tuple[str, str, int]] = set()
    for case_id in case_ids:
        expected.add((ORACLE_METHOD_ID, case_id, DIRECT_MARKET_SEEDS[0]))
        for method_id in DIRECT_MARKET_METHOD_IDS:
            method = registry.create(method_id)
            panel = DIRECT_MARKET_SEEDS if method.spec.stochastic else DIRECT_MARKET_SEEDS[:1]
            expected.update((method_id, case_id, seed) for seed in panel)
    return expected


def audit_direct_market_runs(
    rows: Iterable[DirectMarketRun],
    cases: Iterable[ProcurementCase] | Iterable[str],
) -> tuple[str, ...]:
    """Audit exact run coverage and finite, separated outcome constructs."""

    materialized = tuple(rows)
    case_values = tuple(cases)
    case_ids = tuple(
        item if isinstance(item, str) else item.case_id for item in case_values
    )
    errors: list[str] = []
    observed: set[tuple[str, str, int]] = set()
    run_ids: set[str] = set()
    for row in materialized:
        key = (row.method_id, row.case_id, row.seed)
        if key in observed:
            errors.append(f"duplicate_run:{row.method_id}:{row.case_id}:{row.seed}")
        observed.add(key)
        if row.run_id in run_ids:
            errors.append(f"duplicate_run_id:{row.run_id}")
        run_ids.add(row.run_id)
        if row.status != "completed":
            errors.append(f"noncompleted_run:{row.run_id}:{row.status}")
            continue
        if row.oracle_ratio is None or not math.isfinite(row.oracle_ratio):
            errors.append(f"invalid_oracle_ratio:{row.run_id}")
        elif not 0 <= row.oracle_ratio <= 1 + 1e-12:
            errors.append(f"out_of_range_oracle_ratio:{row.run_id}")
        if row.realized_utility is None or not math.isfinite(row.realized_utility):
            errors.append(f"invalid_realized_utility:{row.run_id}")
        if row.method_role == "headline":
            if row.payment_complete is None or row.budget_violation is None:
                errors.append(f"missing_guardrail:{row.run_id}")
            if row.payment_complete and row.seller_ir_violation_count is None:
                errors.append(f"missing_ir_audit:{row.run_id}")
    expected = _expected_keys(case_ids)
    for method_id, case_id, seed in sorted(expected - observed):
        errors.append(f"missing_run:{method_id}:{case_id}:{seed}")
    for method_id, case_id, seed in sorted(observed - expected):
        errors.append(f"unexpected_run:{method_id}:{case_id}:{seed}")
    return tuple(sorted(set(errors)))


def _case_method_means(
    rows: Iterable[DirectMarketRun],
) -> dict[tuple[str, str, str], float]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.method_role != "headline" or row.status != "completed":
            continue
        assert row.oracle_ratio is not None
        grouped[(row.cohort_id, row.case_id, row.method_id)].append(row.oracle_ratio)
    return {key: fmean(values) for key, values in grouped.items()}


def summarize_cohort_methods(
    rows: Iterable[DirectMarketRun],
) -> tuple[CohortMethodSummary, ...]:
    materialized = tuple(rows)
    grouped: dict[tuple[str, str], list[DirectMarketRun]] = defaultdict(list)
    for row in materialized:
        if row.method_role == "headline" and row.status == "completed":
            grouped[(row.cohort_id, row.method_id)].append(row)
    summaries: list[CohortMethodSummary] = []
    for (cohort_id, method_id), cohort_rows in sorted(grouped.items()):
        by_case: dict[str, list[DirectMarketRun]] = defaultdict(list)
        for row in cohort_rows:
            by_case[row.case_id].append(row)
        case_oracle = [
            fmean(row.oracle_ratio for row in panel if row.oracle_ratio is not None)
            for panel in by_case.values()
        ]
        case_budget = [
            fmean(float(not row.budget_violation) for row in panel)
            for panel in by_case.values()
        ]
        case_complete = [
            fmean(float(bool(row.payment_complete)) for row in panel)
            for panel in by_case.values()
        ]
        auditable = [
            row
            for row in cohort_rows
            if row.payment_complete and row.seller_ir_violation_count is not None
        ]
        first = cohort_rows[0]
        summaries.append(CohortMethodSummary(
            method_id=method_id,
            cohort_id=cohort_id,
            platform=first.platform,
            price_mode=first.price_mode,
            source_listing_count=first.source_listing_count,
            case_count=len(by_case),
            run_count=len(cohort_rows),
            macro_oracle_ratio=fmean(case_oracle),
            worst_case_oracle_ratio=min(case_oracle),
            budget_feasible_rate=fmean(case_budget),
            payment_complete_rate=fmean(case_complete),
            seller_ir_auditable_rate=len(auditable) / len(cohort_rows),
            seller_ir_pass_rate=(
                fmean(float(row.seller_ir_violation_count == 0) for row in auditable)
                if auditable
                else 0.0
            ),
        ))
    return tuple(summaries)


def summarize_methods(
    summaries: Iterable[CohortMethodSummary],
) -> tuple[DirectMethodSummary, ...]:
    grouped: dict[str, list[CohortMethodSummary]] = defaultdict(list)
    for item in summaries:
        grouped[item.method_id].append(item)
    results: list[DirectMethodSummary] = []
    for method_id, items in sorted(grouped.items()):
        worst = min(items, key=lambda item: (item.macro_oracle_ratio, item.cohort_id))
        values = [item.macro_oracle_ratio for item in items]
        results.append(DirectMethodSummary(
            method_id=method_id,
            cohort_count=len(items),
            case_count=sum(item.case_count for item in items),
            run_count=sum(item.run_count for item in items),
            macro_oracle_ratio=fmean(values),
            worst_cohort_oracle_ratio=min(values),
            best_cohort_oracle_ratio=max(values),
            support_range=max(values) - min(values),
            worst_cohort_id=worst.cohort_id,
            budget_feasible_rate=fmean(item.budget_feasible_rate for item in items),
            payment_complete_rate=fmean(item.payment_complete_rate for item in items),
            seller_ir_auditable_rate=fmean(
                item.seller_ir_auditable_rate for item in items
            ),
            seller_ir_pass_rate=fmean(item.seller_ir_pass_rate for item in items),
        ))
    return tuple(results)


def _sign_pattern(values: Iterable[float]) -> str:
    signs = {0 if abs(value) <= 1e-12 else (1 if value > 0 else -1) for value in values}
    if signs == {1}:
        return "positive"
    if signs == {-1}:
        return "negative"
    if signs == {0}:
        return "zero"
    return "mixed"


def compare_chile_contrasts(
    rows: Iterable[DirectMarketRun],
    chile_evidence: Mapping[str, Any],
) -> tuple[TransferContrast, ...]:
    materialized = tuple(rows)
    means = _case_method_means(materialized)
    cohort_meta = {
        row.cohort_id: (row.platform, row.price_mode)
        for row in materialized
        if row.method_role == "headline"
    }
    contrasts = chile_evidence["tracks"]["procurement"]["contrasts"]
    output: list[TransferContrast] = []
    for contrast in contrasts:
        contrast_id = str(contrast["contrast_id"])
        if contrast_id not in {"P-CGLR-vs-GPS", "P-JTDEOM-vs-GPS"}:
            continue
        method_a = str(contrast["method_a"])
        method_b = str(contrast["method_b"])
        chile_values = [float(value) for value in contrast["block_effects"].values()]
        chile_min, chile_max = min(chile_values), max(chile_values)
        for cohort_id in sorted(cohort_meta):
            a = [
                value
                for (cohort, case_id, method), value in means.items()
                if cohort == cohort_id and method == method_a
            ]
            b = [
                value
                for (cohort, case_id, method), value in means.items()
                if cohort == cohort_id and method == method_b
            ]
            if len(a) != len(b) or not a:
                raise ValueError(f"unmatched direct contrast panel:{contrast_id}:{cohort_id}")
            direct = fmean(a) - fmean(b)
            platform, mode = cohort_meta[cohort_id]
            output.append(TransferContrast(
                contrast_id=contrast_id,
                method_a=method_a,
                method_b=method_b,
                cohort_id=cohort_id,
                platform=platform,
                price_mode=mode,
                direct_effect=direct,
                chile_effect_min=chile_min,
                chile_effect_max=chile_max,
                chile_sign_pattern=_sign_pattern(chile_values),
                outside_chile_range=direct < chile_min or direct > chile_max,
                comparison_scope="descriptive_support_transfer_not_population_inference",
            ))
    return tuple(output)


def _findings(
    rows: tuple[DirectMarketRun, ...],
    cohort_summaries: tuple[CohortMethodSummary, ...],
    method_summaries: tuple[DirectMethodSummary, ...],
    contrasts: tuple[TransferContrast, ...],
) -> dict[str, Any]:
    contrast_findings = []
    for contrast_id in sorted({item.contrast_id for item in contrasts}):
        items = [item for item in contrasts if item.contrast_id == contrast_id]
        values = [item.direct_effect for item in items]
        contrast_findings.append({
            "finding_id": f"direct_support_{contrast_id.lower().replace('-', '_')}",
            "contrast_id": contrast_id,
            "direct_effect_min": min(values),
            "direct_effect_max": max(values),
            "direct_sign_pattern": _sign_pattern(values),
            "outside_chile_range_count": sum(item.outside_chile_range for item in items),
            "cohort_count": len(items),
            "claim_scope": "descriptive_support_transfer",
        })
    most_sensitive = max(
        method_summaries, key=lambda item: (item.support_range, item.method_id)
    )
    least_sensitive = min(
        method_summaries, key=lambda item: (item.support_range, item.method_id)
    )
    constraint_finding = {
        "finding_id": "constraints_remain_separate_from_efficiency",
        "minimum_budget_feasible_rate": min(
            item.budget_feasible_rate for item in cohort_summaries
        ),
        "minimum_payment_complete_rate": min(
            item.payment_complete_rate for item in cohort_summaries
        ),
        "minimum_seller_ir_auditable_rate": min(
            item.seller_ir_auditable_rate for item in cohort_summaries
        ),
        "minimum_seller_ir_pass_rate": min(
            item.seller_ir_pass_rate for item in cohort_summaries
        ),
        "claim_scope": "observed_guardrails_on_fixed_listing_support",
    }
    return {
        "schema_version": "1.0",
        "evidence_tier": "exploratory_direct_listing_support",
        "heldout_evidence": False,
        "independent_market_count": 0,
        "price_semantics": "listed_asks_not_transactions_or_costs",
        "seed_semantics": "mechanism_randomness_conditional_on_case",
        "raw_run_count": len(rows),
        "cohort_count": len({row.cohort_id for row in rows}),
        "findings": [
            *contrast_findings,
            {
                "finding_id": "mechanism_support_sensitivity_is_heterogeneous",
                "most_sensitive_method": most_sensitive.method_id,
                "largest_support_range": most_sensitive.support_range,
                "least_sensitive_method": least_sensitive.method_id,
                "smallest_support_range": least_sensitive.support_range,
                "claim_scope": "within_eight_normalized_listing_cohorts",
            },
            constraint_finding,
        ],
        "claim_boundaries": {
            "population_inference": False,
            "realized_transactions": False,
            "latent_reservation_costs": False,
            "incentive_theorem_evaluated": False,
        },
    }


def _csv_bytes(rows: Iterable[Mapping[str, Any]]) -> tuple[bytes, int]:
    materialized = list(rows)
    if not materialized:
        raise ValueError("cannot write an empty CSV artifact")
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(materialized[0]))
    writer.writeheader()
    writer.writerows(materialized)
    return stream.getvalue().encode("utf-8"), len(materialized)


def _report(
    method_summaries: tuple[DirectMethodSummary, ...],
    contrasts: tuple[TransferContrast, ...],
    findings: Mapping[str, Any],
) -> str:
    lines = [
        "# Direct data-market listing-support transfer audit",
        "",
        "This exploratory study uses normalized, public listed asks from DaDaDa. "
        "They are not realized transactions or latent reservation costs. Platform × "
        "price-mode cohorts are descriptive supports, not IID market samples.",
        "",
        "| method | macro oracle ratio | worst cohort | support range | budget feasible | payment complete | seller IR pass |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for item in method_summaries:
        lines.append(
            f"| `{item.method_id}` | {item.macro_oracle_ratio:.3f} | "
            f"`{item.worst_cohort_id}` | {item.support_range:.3f} | "
            f"{item.budget_feasible_rate:.3f} | {item.payment_complete_rate:.3f} | "
            f"{item.seller_ir_pass_rate:.3f} |"
        )
    lines.extend(["", "## Registered-procurement contrast transfer", ""])
    for contrast_id in sorted({item.contrast_id for item in contrasts}):
        items = [item for item in contrasts if item.contrast_id == contrast_id]
        values = [item.direct_effect for item in items]
        lines.append(
            f"- `{contrast_id}` ranges from {min(values):.3f} to {max(values):.3f} "
            f"across {len(items)} direct-listing cohorts; "
            f"{sum(item.outside_chile_range for item in items)} lie outside the "
            "three-block ChileCompra effect range."
        )
    sensitivity = next(
        item
        for item in findings["findings"]
        if item["finding_id"] == "mechanism_support_sensitivity_is_heterogeneous"
    )
    lines.extend([
        "",
        "## Support-shape sensitivity",
        "",
        f"The largest mechanism range is {sensitivity['largest_support_range']:.3f} "
        f"for `{sensitivity['most_sensitive_method']}`; the smallest is "
        f"{sensitivity['smallest_support_range']:.3f} for "
        f"`{sensitivity['least_sensitive_method']}`. Efficiency and each payment "
        "guardrail remain separate columns.",
        "",
        "## Claim boundary",
        "",
        "The study is exploratory support transfer. Seeds quantify mechanism "
        "randomness conditional on fixed cases. Do not interpret cohort variation as "
        "population uncertainty, or infer transactions, private costs, causal platform "
        "effects, or incentive theorems.",
        "",
    ])
    return "\n".join(lines)


def build_direct_market_transfer_artifacts(
    datasets: Mapping[str, Any],
    profiles_path: Path,
    chile_evidence_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Execute and write the deterministic direct-market transfer artifact."""

    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    chile = json.loads(chile_evidence_path.read_text(encoding="utf-8"))
    cases = make_direct_market_procurement_cases(datasets, profiles)
    rows = run_direct_market_transfer(cases)
    errors = audit_direct_market_runs(rows, cases)
    if errors:
        raise ValueError(f"direct-market run audit failed: {errors}")
    cohort_summaries = summarize_cohort_methods(rows)
    method_summaries = summarize_methods(cohort_summaries)
    contrasts = compare_chile_contrasts(rows, chile)
    findings = _findings(rows, cohort_summaries, method_summaries, contrasts)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_bytes = b"".join(
        json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n"
        for row in rows
    )
    payloads: dict[str, tuple[bytes, int | None]] = {
        "raw_runs.jsonl": (raw_bytes, len(rows)),
        "cohort_method_summary.csv": _csv_bytes(
            item.to_dict() for item in cohort_summaries
        ),
        "method_summary.csv": _csv_bytes(item.to_dict() for item in method_summaries),
        "transfer_contrasts.csv": _csv_bytes(item.to_dict() for item in contrasts),
        "findings.json": (_canonical_json(findings), len(findings["findings"])),
        "report.md": (_report(method_summaries, contrasts, findings).encode("utf-8"), None),
    }
    outputs: dict[str, dict[str, Any]] = {}
    for name in OUTPUT_NAMES:
        content, row_count = payloads[name]
        path = output_dir / name
        _atomic_write(path, content)
        outputs[name] = {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "row_count": row_count,
        }
    manifest = {
        "schema_version": "1.0",
        "study_id": "kdd2027-direct-market-price-transfer-v1",
        "claim_scope": "exploratory_direct_listing_support_transfer",
        "heldout_evidence": False,
        "raw_csv_release_member": False,
        "case_count": len(cases),
        "raw_run_count": len(rows),
        "cohort_method_count": len(cohort_summaries),
        "method_count": len(method_summaries),
        "transfer_contrast_count": len(contrasts),
        "method_ids": list(DIRECT_MARKET_METHOD_IDS),
        "oracle_method_id": ORACLE_METHOD_ID,
        "seeds": list(DIRECT_MARKET_SEEDS),
        "case_ids": sorted(case.case_id for case in cases),
        "inputs": {
            "profiles": {
                "path": profiles_path.name,
                "sha256": _sha256(profiles_path),
            },
            "chile_evidence": {
                "path": chile_evidence_path.name,
                "scientific_scope": "/tracks/procurement/contrasts/{P-CGLR-vs-GPS,P-JTDEOM-vs-GPS}",
                "scientific_sha256": _chile_contrast_scientific_sha256(chile),
            },
        },
        "outputs": outputs,
    }
    _atomic_write(output_dir / "manifest.json", _canonical_json(manifest))
    verified = verify_direct_market_transfer_artifacts(
        output_dir, profiles_path, chile_evidence_path
    )
    if not verified["valid"]:
        raise ValueError(f"built direct-market artifacts failed verification: {verified}")
    return {
        "raw_run_count": len(rows),
        "cohort_method_count": len(cohort_summaries),
        "method_count": len(method_summaries),
        "transfer_contrast_count": len(contrasts),
        "manifest_sha256": _sha256(output_dir / "manifest.json"),
    }


def verify_direct_market_transfer_artifacts(
    output_dir: Path,
    profiles_path: Path,
    chile_evidence_path: Path,
) -> dict[str, Any]:
    """Verify input bindings, every output hash, and the exact run panel."""

    errors: list[str] = []
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return {"valid": False, "errors": ["missing:manifest.json"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if not profiles_path.is_file():
        errors.append("missing_input:profiles")
    elif (
        manifest.get("inputs", {}).get("profiles", {}).get("sha256")
        != _sha256(profiles_path)
    ):
        errors.append("input_hash_mismatch:profiles")
    if not chile_evidence_path.is_file():
        errors.append("missing_input:chile_evidence")
    else:
        try:
            chile = json.loads(chile_evidence_path.read_text(encoding="utf-8"))
            observed_chile_hash = _chile_contrast_scientific_sha256(chile)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid_input:chile_evidence:{type(exc).__name__}")
        else:
            expected_chile_hash = (
                manifest.get("inputs", {})
                .get("chile_evidence", {})
                .get("scientific_sha256")
            )
            if expected_chile_hash != observed_chile_hash:
                errors.append("input_scientific_hash_mismatch:chile_evidence")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        return {"valid": False, "errors": [*errors, "outputs_not_mapping"]}
    for name in OUTPUT_NAMES:
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing_output:{name}")
            continue
        if outputs.get(name, {}).get("sha256") != _sha256(path):
            errors.append(f"output_hash_mismatch:{name}")
    raw_path = output_dir / "raw_runs.jsonl"
    if raw_path.is_file():
        try:
            rows = tuple(
                DirectMarketRun.from_dict(json.loads(line))
                for line in raw_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"invalid_raw_runs:{type(exc).__name__}")
        else:
            errors.extend(audit_direct_market_runs(rows, manifest.get("case_ids", ())))
            if len(rows) != manifest.get("raw_run_count"):
                errors.append("raw_run_count_mismatch")
    if manifest.get("raw_csv_release_member") is not False:
        errors.append("raw_csv_release_boundary_missing")
    if manifest.get("heldout_evidence") is not False:
        errors.append("heldout_boundary_missing")
    return {"valid": not errors, "errors": sorted(set(errors))}


def load_frozen_openml_games(repository_root: Path) -> dict[str, Any]:
    """Rebuild the three held-out owner games from hash-checked OpenML files."""

    config_path = repository_root / "benchmark" / "configs" / "kdd_heldout_confirmatory.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw_dir = repository_root / "benchmark" / "data" / "heldout" / "raw" / "openml"
    games: dict[str, Any] = {}
    for source in config["sources"]["valuation"]:
        openml_id = int(source["openml_id"])
        filename, target = OPENML_FILES[openml_id]
        path = raw_dir / filename
        observed_md5 = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        if observed_md5 != source["expected_md5"]:
            raise ValueError(f"OpenML MD5 mismatch:{source['source_id']}")
        games[str(source["source_id"])] = build_owner_dataset_from_arff(
            path,
            dataset_id=str(source["source_id"]),
            target_attribute=target,
            seed=int(config["transformations"]["valuation"]["split_seed"]),
            maximum_rows=int(config["transformations"]["valuation"]["maximum_rows"]),
        )
    return games


__all__ = [
    "DEFAULT_CHILE_EVIDENCE",
    "DEFAULT_OUTPUT",
    "DEFAULT_PROFILES",
    "DIRECT_MARKET_METHOD_IDS",
    "DIRECT_MARKET_SEEDS",
    "CohortMethodSummary",
    "DirectMarketRun",
    "DirectMethodSummary",
    "TransferContrast",
    "audit_direct_market_runs",
    "build_direct_market_transfer_artifacts",
    "compare_chile_contrasts",
    "load_frozen_openml_games",
    "make_direct_market_procurement_cases",
    "run_direct_market_transfer",
    "summarize_cohort_methods",
    "summarize_methods",
    "verify_direct_market_transfer_artifacts",
]
