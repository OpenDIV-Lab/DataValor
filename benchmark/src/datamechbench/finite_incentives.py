"""Claim-safe exhaustive report audits on a declared finite type domain."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .catalog import load_catalog
from .models import MarketOutcome, ProcurementInput, TradeInput
from .registry import MethodRegistry

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / "catalog" / "finite_incentive_audit.yaml"
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "outputs" / "kdd_finite_incentives"
DEFAULT_EVIDENCE = PACKAGE_ROOT / "evidence" / "kdd_finite_incentive_audit_v1.json"
ALLOWED_CONCLUSIONS = {
    "no_counterexample_complete_finite_domain",
    "no_counterexample_complete_reports_seed_panel",
    "counterexample_within_audited_domain",
}
_PROHIBITED_CONCLUSION = re.compile(r"\b(truthful|dsic|bic|proof)\b", re.IGNORECASE)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - Decimal exception types vary by Python
        raise ValueError(f"{label} must be a decimal number") from exc
    if not number.is_finite():
        raise ValueError(f"{label} must be finite")
    return number


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


def _validate_domain(config: Mapping[str, Any]) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], tuple[int, ...], Decimal]:
    true_types = tuple(_decimal(item, "true_types") for item in config.get("true_types", ()))
    reports = tuple(_decimal(item, "reports") for item in config.get("reports", ()))
    seeds = tuple(int(item) for item in config.get("seeds", ()))
    tolerance = _decimal(config.get("tolerance", "1e-9"), "tolerance")
    if not true_types:
        raise ValueError("true_types must be non-empty")
    if not reports:
        raise ValueError("reports must be non-empty")
    if len(set(true_types)) != len(true_types):
        raise ValueError("true_types must be unique")
    if len(set(reports)) != len(reports):
        raise ValueError("reports must be unique")
    if not set(true_types).issubset(reports):
        raise ValueError("reports must contain every true type")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be non-empty and unique")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    return true_types, reports, seeds, tolerance


def load_finite_incentive_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if raw.get("claim_strength") != "empirical_finite_domain_audit":
        raise ValueError("claim_strength must be empirical_finite_domain_audit")
    _validate_domain({**raw, "seeds": (0,)})
    for track in ("procurement", "trading"):
        section = raw.get(track)
        if not isinstance(section, Mapping):
            raise ValueError(f"missing {track} section")
        methods = section.get("methods")
        if not isinstance(methods, list) or not methods:
            raise ValueError(f"{track}.methods must be a non-empty list")
        ids = [str(item.get("method_id", "")) for item in methods]
        if any(not method_id for method_id in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"{track} method IDs must be non-empty and unique")
        for item in methods:
            _validate_domain({**raw, **section, **item})
    return dict(raw)


def _validate_outcome(outcome: MarketOutcome, actors: set[str]) -> None:
    if not isinstance(outcome, MarketOutcome):
        raise TypeError("mechanism must return MarketOutcome")
    if set(outcome.selected_ids) - actors:
        raise ValueError("outcome selected unknown actors")
    for allocation in outcome.allocations:
        if allocation.actor_id not in actors:
            raise ValueError("allocation contains unknown actor")
        if allocation.counterparty_id is not None and allocation.counterparty_id not in actors | {"buyer", "platform"}:
            raise ValueError("allocation contains unknown counterparty")
        if not allocation.quantity.is_finite() or allocation.quantity < 0:
            raise ValueError("allocation quantity must be finite and non-negative")
    for payment in outcome.payments:
        if payment.payer_id not in actors | {"buyer", "platform"}:
            raise ValueError("payment contains unknown payer")
        if payment.payee_id not in actors | {"buyer", "platform"}:
            raise ValueError("payment contains unknown payee")
        if not payment.amount.is_finite() or payment.amount < 0:
            raise ValueError("payment amount must be finite and non-negative")


def _net_transfer(outcome: MarketOutcome, actor: str) -> Decimal:
    incoming = sum((p.amount for p in outcome.payments if p.payee_id == actor), Decimal("0"))
    outgoing = sum((p.amount for p in outcome.payments if p.payer_id == actor), Decimal("0"))
    result = incoming - outgoing
    if not result.is_finite():
        raise ValueError("net transfer must be finite")
    return result


def _procurement_utility(outcome: MarketOutcome, seller: str, true_cost: Decimal) -> Decimal:
    allocated = seller in outcome.selected_ids or any(
        item.actor_id == seller and item.quantity > 0 for item in outcome.allocations
    )
    utility = _net_transfer(outcome, seller) - (true_cost if allocated else Decimal("0"))
    if not utility.is_finite():
        raise ValueError("procurement utility must be finite")
    return utility


def _trading_utility(
    outcome: MarketOutcome,
    actor: str,
    true_type: Decimal,
    *,
    buyer: bool,
) -> Decimal:
    if buyer:
        quantity = sum(
            (item.quantity for item in outcome.allocations if item.actor_id == actor),
            Decimal("0"),
        )
        utility = true_type * quantity + _net_transfer(outcome, actor)
    else:
        quantity = sum(
            (item.quantity for item in outcome.allocations if item.counterparty_id == actor),
            Decimal("0"),
        )
        utility = _net_transfer(outcome, actor) - true_type * quantity
    if not utility.is_finite():
        raise ValueError("trading utility must be finite")
    return utility


def _source_fields(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": str(source.get("source", "unspecified")),
        "reference_url": str(source.get("reference_url", "")),
        "reference_keys": [str(item) for item in source.get("reference_keys", ())],
        "provenance_kind": str(source.get("provenance_kind", "unspecified")),
        "algorithm_location": str(source.get("algorithm_location", "")),
        "deviations": [str(item) for item in source.get("deviations", ())],
    }


def _empty_summary(
    method_id: str,
    track: str,
    config: Mapping[str, Any],
    source: Mapping[str, Any],
    profile_count: int,
    tie_free_profile_count: int,
    actor_count: int,
    alternative_count: int,
    seeds: Sequence[int],
) -> dict[str, Any]:
    stochastic = bool(config.get("stochastic", False))
    expected = profile_count * actor_count * alternative_count * len(seeds)
    expected_tie_free = tie_free_profile_count * actor_count * alternative_count * len(seeds)
    return {
        "method_id": method_id,
        "track": track,
        **_source_fields(source),
        "expectation": str(config.get("expectation", "not specified")),
        "expected_max_gain": _decimal_text(_decimal(config.get("expected_max_gain", 0), "expected_max_gain")),
        "estimand": "ex_post_fixed_seed_panel" if stochastic else "deterministic_finite_domain",
        "stochastic": stochastic,
        "profile_count": profile_count,
        "tie_free_profile_count": tie_free_profile_count,
        "seed_count": len(seeds),
        "seeds": list(seeds),
        "deviation_evaluation_count": 0,
        "expected_deviation_evaluation_count": expected,
        "tie_free_deviation_evaluation_count": 0,
        "expected_tie_free_deviation_evaluation_count": expected_tie_free,
        "max_gain": "0",
        "tie_free_max_gain": "0",
        "profitable_deviation_count": 0,
        "tie_free_profitable_deviation_count": 0,
        "worst_witness": None,
        "tie_free_worst_witness": None,
        "type_domain_complete": True,
        "report_domain_complete": True,
        "random_support_complete": not stochastic,
    }


def _update_summary(
    summary: dict[str, Any],
    *,
    profile: Mapping[str, Decimal],
    actor: str,
    truthful: Decimal,
    report: Decimal,
    seed: int,
    truthful_utility: Decimal,
    deviating_utility: Decimal,
    tolerance: Decimal,
    tie_free: bool,
) -> None:
    gain = deviating_utility - truthful_utility
    if not gain.is_finite():
        raise ValueError("gain must be finite")
    summary["deviation_evaluation_count"] += 1
    if tie_free:
        summary["tie_free_deviation_evaluation_count"] += 1
    witness = {
        "actor_id": actor,
        "deviating_report": _decimal_text(report),
        "deviating_utility": _decimal_text(deviating_utility),
        "gain": _decimal_text(gain),
        "profile": {name: _decimal_text(value) for name, value in profile.items()},
        "seed": seed,
        "truthful_report": _decimal_text(truthful),
        "truthful_utility": _decimal_text(truthful_utility),
    }
    if gain > _decimal(summary["max_gain"], "max_gain"):
        summary["max_gain"] = _decimal_text(gain)
        summary["worst_witness"] = witness
    if tie_free and gain > _decimal(summary["tie_free_max_gain"], "tie_free_max_gain"):
        summary["tie_free_max_gain"] = _decimal_text(gain)
        summary["tie_free_worst_witness"] = witness
    if gain > tolerance:
        summary["profitable_deviation_count"] += 1
        if tie_free:
            summary["tie_free_profitable_deviation_count"] += 1


def _finish_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if summary["deviation_evaluation_count"] != summary["expected_deviation_evaluation_count"]:
        raise ValueError("incomplete deviation coverage")
    if summary["tie_free_deviation_evaluation_count"] != summary["expected_tie_free_deviation_evaluation_count"]:
        raise ValueError("incomplete tie-free deviation coverage")
    if summary["profitable_deviation_count"]:
        conclusion = "counterexample_within_audited_domain"
    elif summary["stochastic"]:
        conclusion = "no_counterexample_complete_reports_seed_panel"
    else:
        conclusion = "no_counterexample_complete_finite_domain"
    summary["conclusion"] = conclusion
    return summary


def audit_procurement_method(
    method_id: str,
    mechanism: Any,
    config: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    true_types, reports, seeds, tolerance = _validate_domain(config)
    sellers = tuple(str(item) for item in config.get("seller_ids", ()))
    if not sellers or len(set(sellers)) != len(sellers):
        raise ValueError("seller_ids must be non-empty and unique")
    public_values = {seller: float(config.get("public_values", {}).get(seller, 0)) for seller in sellers}
    if any(not math.isfinite(value) for value in public_values.values()):
        raise ValueError("public values must be finite")
    budget = _decimal(config.get("budget", 0), "budget")
    profiles = tuple(itertools.product(true_types, repeat=len(sellers)))
    tie_free_count = sum(len(set(profile)) == len(profile) for profile in profiles)
    summary = _empty_summary(
        method_id,
        "procurement",
        config,
        source,
        len(profiles),
        tie_free_count,
        len(sellers),
        len(reports) - 1,
        seeds,
    )

    def utility(selected: tuple[str, ...]) -> float:
        return sum(public_values[seller] for seller in selected)

    actors = set(sellers)
    for values in profiles:
        profile = dict(zip(sellers, values, strict=True))
        tie_free = len(set(values)) == len(values)
        for seed in seeds:
            truthful_case = ProcurementInput(sellers, profile, budget, utility, public_values)
            truthful_outcome = mechanism.allocate(truthful_case, seed)
            _validate_outcome(truthful_outcome, actors)
            for seller in sellers:
                truthful_utility = _procurement_utility(truthful_outcome, seller, profile[seller])
                for report in reports:
                    if report == profile[seller]:
                        continue
                    reported = {**profile, seller: report}
                    deviating_case = ProcurementInput(sellers, reported, budget, utility, public_values)
                    deviating_outcome = mechanism.allocate(deviating_case, seed)
                    _validate_outcome(deviating_outcome, actors)
                    deviating_utility = _procurement_utility(
                        deviating_outcome, seller, profile[seller]
                    )
                    _update_summary(
                        summary,
                        profile=profile,
                        actor=seller,
                        truthful=profile[seller],
                        report=report,
                        seed=seed,
                        truthful_utility=truthful_utility,
                        deviating_utility=deviating_utility,
                        tolerance=tolerance,
                        tie_free=tie_free,
                    )
    return _finish_summary(summary)


def audit_trading_method(
    method_id: str,
    mechanism: Any,
    config: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    true_types, reports, seeds, tolerance = _validate_domain(config)
    buyers = tuple(str(item) for item in config.get("buyer_ids", ()))
    sellers = tuple(str(item) for item in config.get("seller_ids", ()))
    actor_ids = (*buyers, *sellers)
    if not buyers or not sellers or len(set(actor_ids)) != len(actor_ids):
        raise ValueError("buyer_ids and seller_ids must be non-empty and disjoint")
    profiles = tuple(itertools.product(true_types, repeat=len(actor_ids)))
    tie_free_count = sum(len(set(profile)) == len(profile) for profile in profiles)
    summary = _empty_summary(
        method_id,
        "trading",
        config,
        source,
        len(profiles),
        tie_free_count,
        len(actor_ids),
        len(reports) - 1,
        seeds,
    )
    actors = set(actor_ids)
    for values in profiles:
        profile = dict(zip(actor_ids, values, strict=True))
        tie_free = len(set(values)) == len(values)
        truthful_bids = {buyer: profile[buyer] for buyer in buyers}
        truthful_asks = {seller: profile[seller] for seller in sellers}
        for seed in seeds:
            truthful_case = TradeInput("finite-domain-unit", buyers, sellers, truthful_bids, truthful_asks)
            truthful_outcome = mechanism.clear(truthful_case, seed)
            _validate_outcome(truthful_outcome, actors)
            for actor in actor_ids:
                buyer = actor in truthful_bids
                truthful_utility = _trading_utility(
                    truthful_outcome, actor, profile[actor], buyer=buyer
                )
                for report in reports:
                    if report == profile[actor]:
                        continue
                    bids = {**truthful_bids, **({actor: report} if buyer else {})}
                    asks = {**truthful_asks, **({actor: report} if not buyer else {})}
                    deviating_case = TradeInput("finite-domain-unit", buyers, sellers, bids, asks)
                    deviating_outcome = mechanism.clear(deviating_case, seed)
                    _validate_outcome(deviating_outcome, actors)
                    deviating_utility = _trading_utility(
                        deviating_outcome, actor, profile[actor], buyer=buyer
                    )
                    _update_summary(
                        summary,
                        profile=profile,
                        actor=actor,
                        truthful=profile[actor],
                        report=report,
                        seed=seed,
                        truthful_utility=truthful_utility,
                        deviating_utility=deviating_utility,
                        tolerance=tolerance,
                        tie_free=tie_free,
                    )
    return _finish_summary(summary)


def run_finite_incentive_audit(
    config: Mapping[str, Any],
    registry: MethodRegistry,
    *,
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if config.get("claim_strength") != "empirical_finite_domain_audit":
        raise ValueError("claim_strength must be empirical_finite_domain_audit")
    sources = dict(catalog or load_catalog())
    records: list[dict[str, Any]] = []
    for track in ("procurement", "trading"):
        section = dict(config[track])
        for method_config in section["methods"]:
            method_id = str(method_config["method_id"])
            merged = {**config, **section, **method_config}
            mechanism = registry.create(method_id)
            source = sources.get(method_id, {})
            if track == "procurement":
                record = audit_procurement_method(method_id, mechanism, merged, source)
            else:
                record = audit_trading_method(method_id, mechanism, merged, source)
            records.append(record)
    return {
        "schema_version": "1.0",
        "claim_strength": "empirical_finite_domain_audit",
        "domain": {
            "true_types": [str(item) for item in config["true_types"]],
            "reports": [str(item) for item in config["reports"]],
            "tolerance": str(config["tolerance"]),
        },
        "method_count": len(records),
        "methods": sorted(records, key=lambda item: (item["track"], item["method_id"])),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_result(result: Mapping[str, Any]) -> None:
    if result.get("claim_strength") != "empirical_finite_domain_audit":
        raise ValueError("claim_strength must be empirical_finite_domain_audit")
    methods = result.get("methods")
    if not isinstance(methods, list) or not methods:
        raise ValueError("methods must be a non-empty list")
    for record in methods:
        conclusion = str(record.get("conclusion", ""))
        if conclusion not in ALLOWED_CONCLUSIONS or _PROHIBITED_CONCLUSION.search(conclusion):
            raise ValueError(f"invalid empirical conclusion: {conclusion}")
        if record.get("deviation_evaluation_count") != record.get(
            "expected_deviation_evaluation_count"
        ):
            raise ValueError("incomplete deviation coverage")
        if record.get("tie_free_deviation_evaluation_count") != record.get(
            "expected_tie_free_deviation_evaluation_count"
        ):
            raise ValueError("incomplete tie-free deviation coverage")
        if record.get("stochastic") and record.get("random_support_complete") is not False:
            raise ValueError("randomized audits cannot claim complete random support")


def write_finite_incentive_artifacts(
    result: Mapping[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    evidence_path: str | Path = DEFAULT_EVIDENCE,
) -> dict[str, Any]:
    _validate_result(result)
    output = Path(output_dir)
    evidence = Path(evidence_path)
    output.mkdir(parents=True, exist_ok=True)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    json_path = output / "audit_results.json"
    csv_path = output / "audit_results.csv"
    md_path = output / "audit_results.md"
    json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    columns = (
        "track",
        "method_id",
        "provenance_kind",
        "estimand",
        "profile_count",
        "tie_free_profile_count",
        "seed_count",
        "deviation_evaluation_count",
        "max_gain",
        "tie_free_max_gain",
        "profitable_deviation_count",
        "tie_free_profitable_deviation_count",
        "expected_max_gain",
        "conclusion",
        "report_domain_complete",
        "random_support_complete",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for record in result["methods"]:
        writer.writerow({column: record.get(column, "") for column in columns})
    csv_path.write_text(buffer.getvalue(), encoding="utf-8")
    lines = [
        "# KDD finite-domain incentive audit",
        "",
        "Claim strength: `empirical_finite_domain_audit`. A zero observed gain is not a theoretical proof.",
        "",
        "| Track | Method | Estimand | Max gain | Profitable deviations | Conclusion |",
        "|---|---|---|---:|---:|---|",
    ]
    for record in result["methods"]:
        lines.append(
            f"| {record['track']} | {record['method_id']} | {record['estimand']} | "
            f"{record['max_gain']} | {record['profitable_deviation_count']} | {record['conclusion']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifacts = []
    for path in (json_path, csv_path, md_path):
        artifacts.append(
            {
                "path": Path(os.path.relpath(path.resolve(), evidence.parent.resolve())).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "claim_strength": "empirical_finite_domain_audit",
        "method_count": len(result["methods"]),
        "method_ids": [record["method_id"] for record in result["methods"]],
        "scientific_digest": hashlib.sha256(json_path.read_bytes()).hexdigest(),
        "artifacts": artifacts,
    }
    evidence.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_finite_incentive_artifacts(evidence_path: str | Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    evidence = Path(evidence_path)
    manifest = json.loads(evidence.read_text(encoding="utf-8"))
    errors: list[str] = []
    for artifact in manifest.get("artifacts", ()):
        relative = Path(str(artifact.get("path", "")))
        if relative.is_absolute():
            errors.append(f"absolute artifact path: {relative}")
            continue
        path = (evidence.parent / relative).resolve()
        if not path.is_file():
            errors.append(f"missing artifact: {path.name}")
        elif _sha256(path) != artifact.get("sha256"):
            errors.append(f"sha256 mismatch: {path.name}")
    return {"valid": not errors, "errors": errors, "artifact_count": len(manifest.get("artifacts", ()))}


__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_EVIDENCE",
    "DEFAULT_OUTPUT_DIR",
    "audit_procurement_method",
    "audit_trading_method",
    "load_finite_incentive_config",
    "run_finite_incentive_audit",
    "verify_finite_incentive_artifacts",
    "write_finite_incentive_artifacts",
]
