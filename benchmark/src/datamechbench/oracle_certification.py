"""Exact finite-case certificates for market-track reference oracles."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import BenchmarkResult
from .outcomes import parse_outcome
from .report import load_jsonl_results

ORACLE_METHODS = {
    "procurement": "budget_optimum",
    "trading": "efficient_clearing",
}


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _procurement_certificate(case: Any, row: BenchmarkResult) -> dict[str, Any]:
    sellers = tuple(case.public.seller_ids)
    budget = case.public.budget
    candidates: list[dict[str, Any]] = []
    for size in range(len(sellers) + 1):
        for selected in itertools.combinations(sellers, size):
            cost = sum(
                (case.public.reported_costs[seller] for seller in selected),
                Decimal("0"),
            )
            utility = float(case.public.utility(selected))
            if not math.isfinite(utility):
                raise ValueError(f"nonfinite_utility:procurement:{case.case_id}")
            candidates.append(
                {
                    "selected_ids": list(selected),
                    "reported_cost": str(cost),
                    "utility": utility,
                    "feasible": cost <= budget,
                }
            )
    feasible = [candidate for candidate in candidates if candidate["feasible"]]
    optimum = min(
        feasible,
        key=lambda item: (
            -float(item["utility"]),
            _decimal(item["reported_cost"], "reported_cost"),
            tuple(item["selected_ids"]),
        ),
    )
    if row.outcome is None:
        raise ValueError(f"missing_oracle_outcome:procurement:{case.case_id}")
    outcome = parse_outcome("procurement", row.outcome)
    observed = tuple(outcome.selected_ids)
    if len(observed) != len(set(observed)) or not set(observed) <= set(sellers):
        raise ValueError(f"invalid_oracle_allocation:procurement:{case.case_id}")
    observed_cost = sum(
        (case.public.reported_costs[seller] for seller in observed), Decimal("0")
    )
    observed_utility = float(case.public.utility(observed))
    agreement = (
        list(observed) == optimum["selected_ids"]
        and observed_cost == _decimal(optimum["reported_cost"], "reported_cost")
        and math.isclose(
            observed_utility,
            float(optimum["utility"]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    )
    return {
        "track": "procurement",
        "case_id": case.case_id,
        "oracle_method_id": ORACLE_METHODS["procurement"],
        "oracle_run_id": row.run_id,
        "seller_ids": list(sellers),
        "reported_costs": {
            seller: str(case.public.reported_costs[seller]) for seller in sellers
        },
        "budget": str(budget),
        "domain_size": len(candidates),
        "feasible_candidate_count": len(feasible),
        "candidates": candidates,
        "certified_selected_ids": optimum["selected_ids"],
        "certified_reported_cost": optimum["reported_cost"],
        "certified_objective": optimum["utility"],
        "observed_selected_ids": list(observed),
        "observed_reported_cost": str(observed_cost),
        "observed_objective": observed_utility,
        "agreement": agreement,
        "claim_scope": "exact_exhaustive_certificate_for_this_finite_case",
    }


def _trading_certificate(case: Any, row: BenchmarkResult) -> dict[str, Any]:
    buyers = tuple(
        sorted(case.public.buyer_ids, key=lambda actor: (-case.public.bids[actor], actor))
    )
    sellers = tuple(
        sorted(case.public.seller_ids, key=lambda actor: (case.public.asks[actor], actor))
    )
    cardinalities: list[dict[str, Any]] = []
    for count in range(min(len(buyers), len(sellers)) + 1):
        pairs = tuple(zip(buyers[:count], sellers[:count], strict=True))
        gft = sum(
            (case.public.bids[buyer] - case.public.asks[seller] for buyer, seller in pairs),
            Decimal("0"),
        )
        individually_feasible = all(
            case.public.bids[buyer] >= case.public.asks[seller]
            for buyer, seller in pairs
        )
        cardinalities.append(
            {
                "trade_count": count,
                "pairs": [[buyer, seller] for buyer, seller in pairs],
                "gain_from_trade": str(gft),
                "individually_feasible": individually_feasible,
            }
        )
    optimum = min(
        cardinalities,
        key=lambda item: (
            -_decimal(item["gain_from_trade"], "gain_from_trade"),
            -int(item["trade_count"]),
            tuple(tuple(pair) for pair in item["pairs"]),
        ),
    )
    if row.outcome is None:
        raise ValueError(f"missing_oracle_outcome:trading:{case.case_id}")
    outcome = parse_outcome("trading", row.outcome)
    observed_pairs = tuple(
        (allocation.actor_id, allocation.counterparty_id)
        for allocation in outcome.allocations
    )
    if any(seller is None for _, seller in observed_pairs):
        raise ValueError(f"invalid_oracle_allocation:trading:{case.case_id}")
    observed_gft = sum(
        (
            case.public.bids[buyer]
            - case.public.asks[str(seller)]
            for buyer, seller in observed_pairs
        ),
        Decimal("0"),
    )
    agreement = (
        [[buyer, seller] for buyer, seller in observed_pairs] == optimum["pairs"]
        and observed_gft == _decimal(optimum["gain_from_trade"], "gain_from_trade")
    )
    return {
        "track": "trading",
        "case_id": case.case_id,
        "oracle_method_id": ORACLE_METHODS["trading"],
        "oracle_run_id": row.run_id,
        "buyer_ids": list(case.public.buyer_ids),
        "seller_ids": list(case.public.seller_ids),
        "bids": {
            buyer: str(case.public.bids[buyer]) for buyer in case.public.buyer_ids
        },
        "asks": {
            seller: str(case.public.asks[seller]) for seller in case.public.seller_ids
        },
        "domain_size": len(cardinalities),
        "cardinality_frontier": cardinalities,
        "certified_trade_count": optimum["trade_count"],
        "certified_pairs": optimum["pairs"],
        "certified_objective": optimum["gain_from_trade"],
        "observed_trade_count": len(observed_pairs),
        "observed_pairs": [[buyer, seller] for buyer, seller in observed_pairs],
        "observed_objective": str(observed_gft),
        "agreement": agreement,
        "claim_scope": "exact_sorted_cardinality_certificate_for_this_homogeneous_unit_case",
    }


def certify_reference_oracles(
    results: Iterable[BenchmarkResult],
    *,
    cases: Mapping[str, Iterable[Any]],
) -> dict[str, Any]:
    """Certify finite-case optimality independently of the oracle code path."""

    rows = tuple(results)
    case_index = {
        (track, case.case_id): case
        for track in ORACLE_METHODS
        for case in cases.get(track, ())
    }
    errors: list[str] = []
    certificates: list[dict[str, Any]] = []
    for (track, case_id), case in sorted(case_index.items()):
        oracle_rows = [
            row
            for row in rows
            if row.track == track
            and row.case_id == case_id
            and row.method_id == ORACLE_METHODS[track]
            and row.status == "completed"
        ]
        if len(oracle_rows) != 1:
            errors.append(f"oracle_row_count:{track}:{case_id}:{len(oracle_rows)}")
            continue
        try:
            certificate = (
                _procurement_certificate(case, oracle_rows[0])
                if track == "procurement"
                else _trading_certificate(case, oracle_rows[0])
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"certification_error:{track}:{case_id}:{exc}")
            continue
        certificates.append(certificate)
        if not certificate["agreement"]:
            errors.append(f"oracle_disagreement:{track}:{case_id}")
    observed_keys = {
        (row.track, row.case_id)
        for row in rows
        if row.track in ORACLE_METHODS
        and row.method_id == ORACLE_METHODS[row.track]
        and row.status == "completed"
    }
    for track, case_id in sorted(observed_keys - set(case_index)):
        errors.append(f"unknown_oracle_case:{track}:{case_id}")
    counts = {
        track: sum(item["track"] == track for item in certificates)
        for track in ORACLE_METHODS
    }
    return {
        "schema_version": "1.0",
        "report_kind": "finite_case_reference_oracle_certificate",
        "valid": not errors and len(certificates) == len(case_index),
        "errors": sorted(set(errors)),
        "case_count": len(certificates),
        "track_case_counts": counts,
        "cases": certificates,
        "claim_boundary": (
            "Certificates establish exact optimality only for the enumerated finite "
            "benchmark cases; they are not general mechanism theorems."
        ),
    }


def write_oracle_certificate(
    results_path: str | Path,
    output_path: str | Path,
    *,
    cases: Mapping[str, Iterable[Any]],
) -> Path:
    source = Path(results_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = certify_reference_oracles(load_jsonl_results(source), cases=cases)
    payload.update(
        {
            "result_path": os.path.relpath(source, destination.parent),
            "result_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    )
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _verify_procurement(record: Mapping[str, Any]) -> list[str]:
    case_id = str(record.get("case_id", ""))
    errors: list[str] = []
    sellers = tuple(str(item) for item in record.get("seller_ids", []))
    costs = {str(key): _decimal(value, "reported_cost") for key, value in record.get("reported_costs", {}).items()}
    budget = _decimal(record.get("budget"), "budget")
    candidates = record.get("candidates", [])
    if set(costs) != set(sellers) or len(set(sellers)) != len(sellers):
        return [f"invalid_procurement_inputs:{case_id}"]
    seen: set[tuple[str, ...]] = set()
    feasible: list[Mapping[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        selected = tuple(str(item) for item in candidate.get("selected_ids", []))
        if selected in seen or not set(selected) <= set(sellers):
            errors.append(f"invalid_candidate_partition:procurement:{case_id}")
            continue
        seen.add(selected)
        cost = sum((costs[item] for item in selected), Decimal("0"))
        declared_cost = _decimal(candidate.get("reported_cost"), "reported_cost")
        declared_feasible = candidate.get("feasible") is True
        if cost != declared_cost or declared_feasible != (cost <= budget):
            errors.append(f"candidate_arithmetic_mismatch:procurement:{case_id}")
        if declared_feasible:
            feasible.append(candidate)
    if len(seen) != 2 ** len(sellers) or record.get("domain_size") != len(seen):
        errors.append(f"domain_coverage_mismatch:procurement:{case_id}")
    expected_sets = {
        tuple(selected)
        for size in range(len(sellers) + 1)
        for selected in itertools.combinations(sellers, size)
    }
    if seen != expected_sets:
        errors.append(f"domain_partition_mismatch:procurement:{case_id}")
    if not feasible:
        errors.append(f"missing_feasible_candidate:procurement:{case_id}")
        return errors
    optimum = min(
        feasible,
        key=lambda item: (
            -float(item["utility"]),
            _decimal(item["reported_cost"], "reported_cost"),
            tuple(item["selected_ids"]),
        ),
    )
    if (
        record.get("certified_selected_ids") != optimum.get("selected_ids")
        or not math.isclose(float(record.get("certified_objective")), float(optimum.get("utility")), rel_tol=1e-12, abs_tol=1e-12)
        or _decimal(record.get("certified_reported_cost"), "certified_reported_cost")
        != _decimal(optimum.get("reported_cost"), "reported_cost")
    ):
        errors.append(f"certified_optimum_mismatch:procurement:{case_id}")
    if record.get("agreement") is not True:
        errors.append(f"oracle_disagreement:procurement:{case_id}")
    return errors


def _verify_trading(record: Mapping[str, Any]) -> list[str]:
    case_id = str(record.get("case_id", ""))
    errors: list[str] = []
    buyers = tuple(str(item) for item in record.get("buyer_ids", []))
    sellers = tuple(str(item) for item in record.get("seller_ids", []))
    bids = {str(key): _decimal(value, "bid") for key, value in record.get("bids", {}).items()}
    asks = {str(key): _decimal(value, "ask") for key, value in record.get("asks", {}).items()}
    sorted_buyers = tuple(sorted(buyers, key=lambda actor: (-bids[actor], actor)))
    sorted_sellers = tuple(sorted(sellers, key=lambda actor: (asks[actor], actor)))
    expected: list[dict[str, Any]] = []
    for count in range(min(len(buyers), len(sellers)) + 1):
        pairs = tuple(zip(sorted_buyers[:count], sorted_sellers[:count], strict=True))
        gft = sum((bids[buyer] - asks[seller] for buyer, seller in pairs), Decimal("0"))
        expected.append({
            "trade_count": count,
            "pairs": [[buyer, seller] for buyer, seller in pairs],
            "gain_from_trade": str(gft),
            "individually_feasible": all(bids[buyer] >= asks[seller] for buyer, seller in pairs),
        })
    if record.get("cardinality_frontier") != expected or record.get("domain_size") != len(expected):
        errors.append(f"cardinality_frontier_mismatch:trading:{case_id}")
    optimum = min(
        expected,
        key=lambda item: (
            -_decimal(item["gain_from_trade"], "gain_from_trade"),
            -int(item["trade_count"]),
            tuple(tuple(pair) for pair in item["pairs"]),
        ),
    )
    if (
        record.get("certified_pairs") != optimum["pairs"]
        or record.get("certified_trade_count") != optimum["trade_count"]
        or _decimal(record.get("certified_objective"), "certified_objective")
        != _decimal(optimum["gain_from_trade"], "gain_from_trade")
    ):
        errors.append(f"certified_optimum_mismatch:trading:{case_id}")
    if record.get("agreement") is not True:
        errors.append(f"oracle_disagreement:trading:{case_id}")
    return errors


def verify_oracle_certificate(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    errors: list[str] = []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_certificate:{type(exc).__name__}"], "case_count": 0, "track_case_counts": {}}
    if payload.get("schema_version") != "1.0" or payload.get("report_kind") != "finite_case_reference_oracle_certificate":
        errors.append("invalid_certificate_contract")
    result_path = source.parent / str(payload.get("result_path", ""))
    if not result_path.is_file():
        errors.append("missing_result_file")
    elif hashlib.sha256(result_path.read_bytes()).hexdigest() != payload.get("result_sha256"):
        errors.append("result_hash_mismatch")
    records = payload.get("cases", [])
    if not isinstance(records, list):
        records = []
        errors.append("cases_not_list")
    keys: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            errors.append("invalid_case_record")
            continue
        track = str(record.get("track", ""))
        key = (track, str(record.get("case_id", "")))
        if key in keys:
            errors.append(f"duplicate_case:{track}:{key[1]}")
        keys.add(key)
        try:
            if track == "procurement":
                errors.extend(_verify_procurement(record))
            elif track == "trading":
                errors.extend(_verify_trading(record))
            else:
                errors.append(f"invalid_track:{track}")
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            errors.append(f"invalid_case:{track}:{key[1]}:{exc}")
    counts = {track: sum(key[0] == track for key in keys) for track in ORACLE_METHODS}
    if payload.get("case_count") != len(records) or payload.get("track_case_counts") != counts:
        errors.append("case_count_mismatch")
    if payload.get("valid") is not True or payload.get("errors") != []:
        errors.append("certificate_not_declared_valid")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "case_count": len(records),
        "track_case_counts": counts,
    }


__all__ = [
    "certify_reference_oracles",
    "verify_oracle_certificate",
    "write_oracle_certificate",
]
