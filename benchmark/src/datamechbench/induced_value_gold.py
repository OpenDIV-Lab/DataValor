"""Controlled induced-value cases with replayable mechanism outcomes.

The cases in this module expose evaluator-known types by experimental design.
They provide direct mechanism semantics in a finite controlled domain, not
observations of private preferences in a deployed data market.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import replace
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .models import ProcurementCase, ProcurementInput, TradeCase, TradeInput
from .reference_evaluation import audit_reference_results
from .report import write_jsonl
from .runner import BenchmarkConfig, run_benchmark

HEADLINE_METHODS: Mapping[str, tuple[str, ...]] = {
    "procurement": (
        "generalized_proportional_share",
        "cgl_deterministic",
        "cgl_randomized",
        "jt_greedy_tm",
        "jt_random_eom",
        "jt_deterministic_eom",
    ),
    "trading": (
        "mcafee",
        "trade_reduction",
        "sbba",
        "lottery_muda",
        "vickrey_muda",
    ),
}
PRIMARY_METRICS = {
    "procurement": "oracle_ratio",
    "trading": "gain_from_trade_ratio",
}
OUTPUT_NAMES = (
    "raw_results.jsonl",
    "cases.json",
    "method_profiles.csv",
    "semantic_receipt.json",
    "summary.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _exact_additive_optimum(
    seller_ids: tuple[str, ...],
    values: Mapping[str, float],
    costs: Mapping[str, Decimal],
    budget: Decimal,
) -> tuple[tuple[str, ...], float]:
    best_ids: tuple[str, ...] = ()
    best_value = 0.0
    for size in range(len(seller_ids) + 1):
        for subset in combinations(seller_ids, size):
            if sum((costs[item] for item in subset), Decimal("0")) > budget:
                continue
            value = sum(values[item] for item in subset)
            if value > best_value or (value == best_value and subset < best_ids):
                best_ids, best_value = subset, value
    return best_ids, best_value


def _procurement_case(
    case_id: str,
    *,
    values: tuple[float, ...],
    costs: tuple[str, ...],
    budget: str,
    groups: tuple[str, ...],
    regime: str,
) -> ProcurementCase:
    sellers = tuple(f"seller-{index}" for index in range(len(values)))
    seller_values = dict(zip(sellers, values, strict=True))
    true_costs = {
        seller: Decimal(cost)
        for seller, cost in zip(sellers, costs, strict=True)
    }
    provider_groups = dict(zip(sellers, groups, strict=True))
    budget_value = Decimal(budget)

    def utility(selected: Iterable[str]) -> float:
        return float(sum(seller_values[item] for item in set(selected)))

    exact_ids, exact_value = _exact_additive_optimum(
        sellers, seller_values, true_costs, budget_value
    )
    metadata = {
        "benchmark_setting": "P-INDUCED-VALUE-GOLD",
        "cohort": "controlled_gold",
        "evidence_scope": "controlled_induced_value",
        "private_type_semantic": "induced_by_protocol",
        "outcome_replayable": True,
        "provider_groups": provider_groups,
        "regime": regime,
        "pilot": False,
        "primary_metric_eligible": True,
        "exact_optimum": exact_ids,
        "exact_opt_utility": exact_value,
        "assumptions": (
            "controlled_induced_single_parameter_costs",
            "additive_public_buyer_value",
            "truthful_reports",
            "complete_evaluator_types",
        ),
    }
    return ProcurementCase(
        case_id=case_id,
        public=ProcurementInput(
            seller_ids=sellers,
            reported_costs=true_costs,
            budget=budget_value,
            utility=utility,
            seller_values=seller_values,
            metadata={
                "mechanism_utility": "public_additive_values",
                "benchmark_setting": metadata["benchmark_setting"],
            },
        ),
        true_costs=true_costs,
        case_type="analytic",
        metadata=metadata,
        attack_labels={seller: "truthful" for seller in sellers},
    )


def _trading_case(
    case_id: str,
    *,
    values: tuple[str, ...],
    costs: tuple[str, ...],
    groups: tuple[str, ...],
    regime: str,
) -> TradeCase:
    buyers = tuple(f"buyer-{index}" for index in range(len(values)))
    sellers = tuple(f"seller-{index}" for index in range(len(costs)))
    true_values = {
        buyer: Decimal(value)
        for buyer, value in zip(buyers, values, strict=True)
    }
    true_costs = {
        seller: Decimal(cost)
        for seller, cost in zip(sellers, costs, strict=True)
    }
    provider_groups = dict(zip(sellers, groups, strict=True))
    metadata = {
        "benchmark_setting": "T-INDUCED-VALUE-GOLD",
        "cohort": "controlled_gold",
        "evidence_scope": "controlled_induced_value",
        "private_type_semantic": "induced_by_protocol",
        "outcome_replayable": True,
        "provider_groups": provider_groups,
        "regime": regime,
        "pilot": False,
        "primary_metric_eligible": True,
        "efficient_trade_count": sum(
            value >= cost
            for value, cost in zip(
                sorted(true_values.values(), reverse=True),
                sorted(true_costs.values()),
                strict=True,
            )
        ),
        "market_size": max(len(buyers), len(sellers)),
        "assumptions": (
            "controlled_induced_private_values",
            "single_unit",
            "truthful_reports",
            "complete_evaluator_types",
        ),
    }
    return TradeCase(
        case_id=case_id,
        public=TradeInput(
            product_id=f"{case_id}-data-access",
            buyer_ids=buyers,
            seller_ids=sellers,
            bids=true_values,
            asks=true_costs,
            metadata={"benchmark_setting": metadata["benchmark_setting"]},
        ),
        true_values=true_values,
        true_costs=true_costs,
        case_type="double_auction",
        metadata=metadata,
        attack_labels={actor: "truthful" for actor in (*buyers, *sellers)},
    )


def make_induced_value_cases() -> dict[str, tuple[Any, ...]]:
    """Return deterministic controlled cases with complete evaluator types."""

    procurement = (
        _procurement_case(
            "PIVG-balanced-b40",
            values=(9, 8, 7, 6, 5, 4),
            costs=("2", "3", "4", "5", "6", "7"),
            budget="10",
            groups=("small", "small", "small", "large", "large", "large"),
            regime="balanced",
        ),
        _procurement_case(
            "PIVG-small-efficient",
            values=(8, 8, 7, 6, 5, 4),
            costs=("1", "2", "3", "6", "7", "8"),
            budget="9",
            groups=("small", "small", "small", "large", "large", "large"),
            regime="small_provider_cost_advantage",
        ),
        _procurement_case(
            "PIVG-large-dominant",
            values=(3, 4, 5, 13, 12, 11),
            costs=("2", "3", "4", "7", "7", "8"),
            budget="15",
            groups=("small", "small", "small", "large", "large", "large"),
            regime="large_provider_value_concentration",
        ),
        _procurement_case(
            "PIVG-tight-budget",
            values=(10, 9, 8, 7, 6, 5),
            costs=("3", "4", "5", "6", "7", "8"),
            budget="8",
            groups=("small", "small", "small", "large", "large", "large"),
            regime="tight_budget",
        ),
    )
    trading = (
        _trading_case(
            "TIVG-balanced",
            values=("0.95", "0.85", "0.75", "0.65", "0.30", "0.20"),
            costs=("0.10", "0.20", "0.35", "0.55", "0.80", "0.90"),
            groups=("small", "small", "small", "large", "large", "large"),
            regime="balanced",
        ),
        _trading_case(
            "TIVG-thin-margin",
            values=("0.62", "0.59", "0.56", "0.51", "0.30", "0.20"),
            costs=("0.39", "0.44", "0.49", "0.54", "0.80", "0.90"),
            groups=("small", "small", "small", "large", "large", "large"),
            regime="thin_margin",
        ),
        _trading_case(
            "TIVG-small-low-cost",
            values=("0.95", "0.88", "0.80", "0.70", "0.35", "0.20"),
            costs=("0.05", "0.12", "0.18", "0.52", "0.68", "0.82"),
            groups=("small", "small", "small", "large", "large", "large"),
            regime="small_provider_cost_advantage",
        ),
        _trading_case(
            "TIVG-large-low-cost",
            values=("0.95", "0.88", "0.80", "0.70", "0.35", "0.20"),
            costs=("0.48", "0.58", "0.72", "0.05", "0.12", "0.18"),
            groups=("small", "small", "small", "large", "large", "large"),
            regime="large_provider_cost_advantage",
        ),
    )
    return {"valuation": (), "procurement": procurement, "trading": trading}


def _metric_number(row: Any, metric_id: str) -> float | None:
    metric = row.metrics.get(metric_id)
    applicable = getattr(metric, "applicable", True)
    value = getattr(metric, "value", metric)
    if not applicable or value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _case_payload(cases: Mapping[str, Iterable[Any]]) -> dict[str, Any]:
    procurement = []
    for case in cases["procurement"]:
        procurement.append({
            "case_id": case.case_id,
            "setting_id": case.metadata["benchmark_setting"],
            "evidence_scope": case.metadata["evidence_scope"],
            "regime": case.metadata["regime"],
            "seller_values": dict(case.public.seller_values),
            "true_costs": {key: str(value) for key, value in case.true_costs.items()},
            "budget": str(case.public.budget),
            "provider_groups": dict(case.metadata["provider_groups"]),
        })
    trading = []
    for case in cases["trading"]:
        trading.append({
            "case_id": case.case_id,
            "setting_id": case.metadata["benchmark_setting"],
            "evidence_scope": case.metadata["evidence_scope"],
            "regime": case.metadata["regime"],
            "true_values": {key: str(value) for key, value in case.true_values.items()},
            "true_costs": {key: str(value) for key, value in case.true_costs.items()},
            "provider_groups": dict(case.metadata["provider_groups"]),
        })
    return {
        "schema_version": "1.0",
        "case_bank_kind": "controlled_induced_value_gold",
        "procurement": procurement,
        "trading": trading,
    }


def _write_profiles(path: Path, rows: Iterable[Any]) -> None:
    completed = [row for row in rows if row.status == "completed"]
    profile_rows = []
    for track, method_ids in HEADLINE_METHODS.items():
        for method_id in method_ids:
            selected = [
                row
                for row in completed
                if row.track == track and row.method_id == method_id
            ]
            primary = [
                value
                for row in selected
                if (value := _metric_number(row, PRIMARY_METRICS[track])) is not None
            ]
            profile_rows.append({
                "track": track,
                "method_id": method_id,
                "completed_runs": len(selected),
                "primary_metric": PRIMARY_METRICS[track],
                "primary_mean": fmean(primary) if primary else "",
                "case_count": len({row.case_id for row in selected}),
                "semantic_scope": "controlled_induced_value",
            })
    columns = (
        "track",
        "method_id",
        "completed_runs",
        "case_count",
        "primary_metric",
        "primary_mean",
        "semantic_scope",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(profile_rows)


def build_induced_value_gold(
    output_dir: str | Path,
    repository_root: str | Path,
) -> dict[str, Any]:
    """Run and bind the controlled gold suite."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cases = make_induced_value_cases()
    config = BenchmarkConfig(
        name="kdd-induced-value-gold-v1",
        output_dir=str(output),
        seeds=(1701, 2903, 4703),
        methods={
            "valuation": {},
            "procurement": {method_id: {} for method_id in HEADLINE_METHODS["procurement"]},
            "trading": {method_id: {} for method_id in HEADLINE_METHODS["trading"]},
        },
        case_ids={
            track: tuple(case.case_id for case in track_cases)
            for track, track_cases in cases.items()
        },
        strategic_audit=False,
    )
    raw_results = run_benchmark(config, cases=cases)
    by_case = {
        case.case_id: case for track_cases in cases.values() for case in track_cases
    }
    results = tuple(
        replace(
            row,
            metadata={
                **row.metadata,
                "private_type_semantic": by_case[row.case_id].metadata[
                    "private_type_semantic"
                ],
                "outcome_replayable": True,
                "semantic_claim_boundary": "controlled_not_observed_market",
            },
        )
        for row in raw_results
    )
    write_jsonl(results, output / "raw_results.jsonl")
    _write_json(output / "cases.json", _case_payload(cases))
    _write_profiles(output / "method_profiles.csv", results)

    replay = audit_reference_results(results, cases=cases)
    semantic_receipt = {
        "schema_version": "1.0",
        "evidence_scope": "controlled_induced_value",
        "direct_mechanism_semantics": True,
        "evaluator_known_private_types": True,
        "outcome_replayable": True,
        "observed_market_private_types": False,
        "deployed_market_outcomes": False,
        "claim_boundary": (
            "Induced values are evaluator-known experimental types and not observed "
            "market preferences, deployed data-market bids, or population estimates."
        ),
    }
    _write_json(output / "semantic_receipt.json", semantic_receipt)
    completed = [row for row in results if row.status == "completed"]
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-induced-value-gold-v1",
        "valid": replay.passed and not any(row.status == "failed" for row in results),
        "case_counts": {
            track: len(track_cases)
            for track, track_cases in cases.items()
            if track != "valuation"
        },
        "headline_method_count": len({row.method_id for row in completed}),
        "completed_run_count": len(completed),
        "skipped_run_count": sum(row.status == "skipped" for row in results),
        "failed_run_count": sum(row.status == "failed" for row in results),
        "semantic_scope": "controlled_induced_value",
        "replay_audit": {
            "passed": replay.passed,
            "completed_rows": replay.completed_rows,
            "auditable_rows": replay.auditable_rows,
            "recomputed_metric_count": replay.recomputed_metric_count,
            "metric_mismatch_count": len(replay.metric_mismatches),
            "error_count": len(replay.errors),
        },
        "claim_boundary": semantic_receipt["claim_boundary"],
    }
    _write_json(output / "summary.json", summary)
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "controlled_induced_value_gold",
        "repository_root_role": "source_checkout",
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)}
            for name in OUTPUT_NAMES
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return summary


def verify_induced_value_gold(manifest_path: str | Path) -> dict[str, Any]:
    """Verify a gold-suite manifest without trusting declared validity."""

    path = Path(manifest_path)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"], "output_count": 0}
    outputs = payload.get("outputs")
    if payload.get("schema_version") != "1.0" or not isinstance(outputs, list):
        return {"valid": False, "errors": ["invalid_manifest_schema"], "output_count": 0}
    seen: set[str] = set()
    for record in outputs:
        name = str(record.get("path", "")) if isinstance(record, Mapping) else ""
        expected = str(record.get("sha256", "")) if isinstance(record, Mapping) else ""
        if name in seen or name not in OUTPUT_NAMES:
            errors.append(f"invalid_output:{name or 'missing'}")
            continue
        seen.add(name)
        output = path.parent / name
        if not output.is_file():
            errors.append(f"missing:{name}")
        elif _sha256(output) != expected:
            errors.append(f"hash_mismatch:{name}")
    for missing in sorted(set(OUTPUT_NAMES) - seen):
        errors.append(f"missing_binding:{missing}")
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "HEADLINE_METHODS",
    "build_induced_value_gold",
    "make_induced_value_cases",
    "verify_induced_value_gold",
]
