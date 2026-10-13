"""Prospectively registered theory-boundary challenge panel."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping

import yaml

from .metrics import MetricValue
from .models import ProcurementCase, ProcurementInput, TradeCase, TradeInput
from .oracle_certification import write_oracle_certificate
from .report import load_jsonl_results, write_jsonl
from .runner import BenchmarkConfig, run_benchmark

HEADLINE_METHODS = {
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
ORACLES = {"procurement": "budget_optimum", "trading": "efficient_clearing"}
PRIMARY_METRICS = {"procurement": "oracle_ratio", "trading": "gain_from_trade_ratio"}
OUTPUT_NAMES = (
    "raw_results.jsonl",
    "oracle_certificate.json",
    "per_case.csv",
    "summary.json",
    "report.md",
)
_PROHIBITED_PROTOCOL_KEYS = frozenset(
    {"results", "outcomes", "winner", "ranking", "scores", "leaderboard"}
)


def _find_contamination(raw: Any, prefix: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            name = str(key)
            location = f"{prefix}.{name}" if prefix else name
            if name in _PROHIBITED_PROTOCOL_KEYS or name.startswith("observed_"):
                errors.append(location)
            errors.extend(_find_contamination(value, location))
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            errors.extend(_find_contamination(value, f"{prefix}[{index}]"))
    return errors


def load_challenge_protocol(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0":
        raise ValueError("unsupported challenge protocol")
    if raw.get("cohort") != "diagnostic_challenge":
        raise ValueError("challenge protocol must use diagnostic_challenge cohort")
    contaminated = _find_contamination(raw)
    if contaminated:
        raise ValueError(f"outcome-contaminated protocol: {contaminated}")
    if raw.get("selection_rule") != "theory_boundary_conditions_fixed_before_mechanism_execution":
        raise ValueError("challenge protocol requires prospective selection rule")
    methods = raw.get("headline_methods")
    if not isinstance(methods, Mapping) or {
        track: tuple(methods.get(track, ())) for track in HEADLINE_METHODS
    } != HEADLINE_METHODS:
        raise ValueError("challenge headline methods do not match frozen KDD suite")
    cases = raw.get("cases")
    if not isinstance(cases, Mapping):
        raise ValueError("challenge cases must be a mapping")
    expected_counts = {"procurement": 4, "trading": 5}
    for track, count in expected_counts.items():
        rows = cases.get(track)
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError(f"challenge {track} requires {count} cases")
        identifiers = [str(row.get("case_id", "")) for row in rows if isinstance(row, Mapping)]
        if len(identifiers) != count or len(set(identifiers)) != count or "" in identifiers:
            raise ValueError(f"challenge {track} case IDs must be unique")
    return {str(key): value for key, value in raw.items()}


def _exact_additive_optimum(
    sellers: tuple[str, ...],
    values: Mapping[str, float],
    costs: Mapping[str, Decimal],
    budget: Decimal,
) -> tuple[tuple[str, ...], float]:
    best: tuple[str, ...] = ()
    best_value = 0.0
    for size in range(len(sellers) + 1):
        for selected in itertools.combinations(sellers, size):
            if sum((costs[item] for item in selected), Decimal("0")) > budget:
                continue
            value = sum(values[item] for item in selected)
            if value > best_value or (value == best_value and selected < best):
                best, best_value = selected, value
    return best, best_value


def _procurement_case(raw: Mapping[str, Any]) -> ProcurementCase:
    values_list = tuple(float(value) for value in raw["values"])
    costs_list = tuple(Decimal(str(value)) for value in raw["costs"])
    if len(values_list) != len(costs_list) or not values_list:
        raise ValueError("procurement challenge vectors must be non-empty and aligned")
    sellers = tuple(f"s{index}" for index in range(len(values_list)))
    values = dict(zip(sellers, values_list, strict=True))
    costs = dict(zip(sellers, costs_list, strict=True))
    budget = Decimal(str(raw["budget"]))

    def utility(selected: tuple[str, ...], local_values=values) -> float:
        return float(sum(local_values[item] for item in set(selected)))

    optimum, optimum_value = _exact_additive_optimum(
        sellers, values, costs, budget
    )
    return ProcurementCase(
        case_id=str(raw["case_id"]),
        public=ProcurementInput(
            seller_ids=sellers,
            reported_costs=costs,
            budget=budget,
            utility=utility,
            seller_values=values,
            metadata={"mechanism_utility": "registered_additive_boundary"},
        ),
        true_costs=costs,
        case_type="analytic",
        metadata={
            "benchmark_setting": "P-DIAGNOSTIC-CHALLENGE",
            "cohort": "diagnostic_challenge",
            "evidence_scope": "theory_boundary_diagnostic",
            "independent_block": str(raw["case_id"]),
            "theory_clause": str(raw["theory_clause"]),
            "exact_optimum": optimum,
            "exact_opt_utility": optimum_value,
            "assumptions": (
                "additive_public_values",
                "single_parameter_sellers",
                "complete_true_types",
                "diagnostic_not_population_inference",
            ),
        },
        attack_labels={seller: "truthful" for seller in sellers},
    )


def _trading_case(raw: Mapping[str, Any]) -> TradeCase:
    values_list = tuple(Decimal(str(value)) for value in raw["buyer_values"])
    costs_list = tuple(Decimal(str(value)) for value in raw["seller_costs"])
    buyers = tuple(f"b{index}" for index in range(len(values_list)))
    sellers = tuple(f"s{index}" for index in range(len(costs_list)))
    values = dict(zip(buyers, values_list, strict=True))
    costs = dict(zip(sellers, costs_list, strict=True))
    efficient = sum(
        value >= cost
        for value, cost in zip(
            sorted(values.values(), reverse=True), sorted(costs.values())
        )
    )
    case_id = str(raw["case_id"])
    return TradeCase(
        case_id=case_id,
        public=TradeInput(
            product_id=f"{case_id}-data-access",
            buyer_ids=buyers,
            seller_ids=sellers,
            bids=values,
            asks=costs,
            metadata={"benchmark_setting": "T-DIAGNOSTIC-CHALLENGE"},
        ),
        true_values=values,
        true_costs=costs,
        case_type="double_auction",
        metadata={
            "benchmark_setting": "T-DIAGNOSTIC-CHALLENGE",
            "cohort": "diagnostic_challenge",
            "evidence_scope": "theory_boundary_diagnostic",
            "independent_block": case_id,
            "theory_clause": str(raw["theory_clause"]),
            "efficient_trade_count": efficient,
            "assumptions": (
                "single_unit",
                "complete_true_types",
                "truthful_reports",
                "diagnostic_not_population_inference",
            ),
        },
        attack_labels={actor: "truthful" for actor in (*buyers, *sellers)},
    )


def make_challenge_cases(
    protocol: Mapping[str, Any],
) -> dict[str, tuple[Any, ...]]:
    cases = protocol["cases"]
    return {
        "valuation": (),
        "procurement": tuple(_procurement_case(row) for row in cases["procurement"]),
        "trading": tuple(_trading_case(row) for row in cases["trading"]),
    }


def _metric_number(row: Any, metric_id: str) -> float | None:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        if not raw.applicable:
            return None
        raw = raw.value
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _metric_bool(row: Any, metric_id: str) -> bool | None:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        if not raw.applicable:
            return None
        raw = raw.value
    return raw if isinstance(raw, bool) else None


def _summarize(results: tuple[Any, ...], tolerance: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    per_case: list[dict[str, Any]] = []
    quality_index: dict[tuple[str, str, str], float] = {}
    for track, methods in HEADLINE_METHODS.items():
        for method in methods:
            method_rows = [
                row for row in results
                if row.track == track and row.method_id == method and row.status == "completed"
            ]
            for case_id in sorted({row.case_id for row in method_rows}):
                rows = [row for row in method_rows if row.case_id == case_id]
                qualities = [
                    _metric_number(row, PRIMARY_METRICS[track]) for row in rows
                ]
                quality = fmean(value for value in qualities if value is not None)
                quality_index[(track, method, case_id)] = quality
                usage_rows = [
                    row.outcome.get("diagnostics", {}).get("resource_usage", {})
                    for row in rows
                    if isinstance(row.outcome, Mapping)
                ]
                units = sorted({key for usage in usage_rows for key in usage})
                usage = {
                    unit: fmean(float(item[unit]) for item in usage_rows)
                    for unit in units
                }
                if track == "procurement":
                    constraint_failures = sum(
                        _metric_bool(row, "budget_violation") is True
                        or (_metric_number(row, "seller_ir_violation_count") or 0) > 0
                        for row in rows
                    )
                else:
                    constraint_failures = sum(
                        _metric_bool(row, "individual_rationality") is False
                        or _metric_bool(row, "weak_budget_balance") is False
                        for row in rows
                    )
                per_case.append(
                    {
                        "track": track,
                        "case_id": case_id,
                        "method_id": method,
                        "primary_metric_id": PRIMARY_METRICS[track],
                        "mean_primary_metric": quality,
                        "resource_usage": usage,
                        "constraint_failure_runs": constraint_failures,
                        "run_count": len(rows),
                    }
                )
    separated_cells: dict[str, int] = {}
    separable_pairs: dict[str, int] = {}
    pair_counts: dict[str, int] = {}
    case_resolution: list[dict[str, Any]] = []
    strongest_cases: dict[str, str] = {}
    for track, methods in HEADLINE_METHODS.items():
        case_ids = sorted({row[2] for row in quality_index if row[0] == track})
        pairs = tuple(itertools.combinations(methods, 2))
        pair_counts[track] = len(pairs)
        separated_cells[track] = sum(
            abs(quality_index[(track, left, case_id)] - quality_index[(track, right, case_id)]) > tolerance
            for left, right in pairs
            for case_id in case_ids
        )
        separable_pairs[track] = sum(
            any(
                abs(quality_index[(track, left, case_id)] - quality_index[(track, right, case_id)]) > tolerance
                for case_id in case_ids
            )
            for left, right in pairs
        )
        track_cases: list[dict[str, Any]] = []
        for case_id in case_ids:
            values = [quality_index[(track, method, case_id)] for method in methods]
            record = {
                "track": track,
                "case_id": case_id,
                "separated_pair_count": sum(
                    abs(quality_index[(track, left, case_id)] - quality_index[(track, right, case_id)])
                    > tolerance
                    for left, right in pairs
                ),
                "pair_count": len(pairs),
                "quality_min": min(values),
                "quality_max": max(values),
                "quality_range": max(values) - min(values),
                "constraint_failure_method_count": sum(
                    row["constraint_failure_runs"] > 0
                    for row in per_case
                    if row["track"] == track and row["case_id"] == case_id
                ),
            }
            track_cases.append(record)
            case_resolution.append(record)
        strongest_cases[track] = max(
            track_cases,
            key=lambda row: (row["separated_pair_count"], -case_ids.index(row["case_id"])),
        )["case_id"]
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-diagnostic-challenge-v1",
        "valid": bool(per_case),
        "case_counts": {"procurement": 4, "trading": 5},
        "headline_method_counts": {
            track: len(methods) for track, methods in HEADLINE_METHODS.items()
        },
        "pair_counts": pair_counts,
        "separated_case_relations": separated_cells,
        "separable_pair_counts": separable_pairs,
        "case_resolution": case_resolution,
        "strongest_cases": strongest_cases,
        "practical_tolerance": tolerance,
        "claim_boundary": (
            "Theory-boundary diagnostic evidence only; results cannot be pooled "
            "with held-out source blocks or interpreted as population rankings."
        ),
    }
    return summary, per_case


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_challenge_panel(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    protocol_path: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root)
    protocol_source = Path(protocol_path)
    if not protocol_source.is_absolute():
        protocol_source = root / protocol_source
    protocol = load_challenge_protocol(protocol_source)
    cases = make_challenge_cases(protocol)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    methods = {
        "valuation": {},
        "procurement": {method: {} for method in (*HEADLINE_METHODS["procurement"], ORACLES["procurement"])},
        "trading": {method: {} for method in (*HEADLINE_METHODS["trading"], ORACLES["trading"])},
    }
    config = BenchmarkConfig(
        name=str(protocol["study_id"]),
        output_dir=str(output),
        seeds=tuple(int(seed) for seed in protocol["random_seeds"]),
        methods=methods,
        case_ids={track: tuple(case.case_id for case in track_cases) for track, track_cases in cases.items()},
        strategic_audit=False,
    )
    results = run_benchmark(config, cases=cases)
    if any(row.status != "completed" for row in results):
        failed = [f"{row.track}/{row.method_id}/{row.case_id}:{row.status}" for row in results if row.status != "completed"]
        raise ValueError(f"challenge panel incomplete: {failed}")
    results_path = write_jsonl(results, output / "raw_results.jsonl")
    write_oracle_certificate(
        results_path,
        output / "oracle_certificate.json",
        cases=cases,
    )
    summary, per_case = _summarize(results, float(protocol["practical_tolerance"]))
    columns = (
        "track", "case_id", "method_id", "primary_metric_id",
        "mean_primary_metric", "resource_usage_json", "constraint_failure_runs", "run_count",
    )
    with (output / "per_case.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in per_case:
            writer.writerow({
                **{key: row[key] for key in columns if key != "resource_usage_json"},
                "resource_usage_json": json.dumps(row["resource_usage"], sort_keys=True, separators=(",", ":")),
            })
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# Diagnostic challenge panel",
        "",
        "This panel probes registered theory boundaries and is not held-out population evidence.",
        "",
        "| Track | Cases | Headline methods | Separable pairs | All pairs | Separated pair-cells |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for track in HEADLINE_METHODS:
        report.append(
            f"| {track} | {summary['case_counts'][track]} | "
            f"{summary['headline_method_counts'][track]} | "
            f"{summary['separable_pair_counts'][track]} | "
            f"{summary['pair_counts'][track]} | "
            f"{summary['separated_case_relations'][track]} |"
        )
    report.extend(
        [
            "",
            "## Case-level resolution",
            "",
            "Separated pairs use the prospectively frozen practical tolerance; this is diagnostic resolution, not a ranking claim.",
            "",
            "| Track | Case | Separated pairs | All pairs | Quality range | Constraint-failure methods |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary["case_resolution"]:
        report.append(
            f"| {row['track']} | {row['case_id']} | {row['separated_pair_count']} | "
            f"{row['pair_count']} | {row['quality_range']:.6f} | "
            f"{row['constraint_failure_method_count']} |"
        )
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "diagnostic_challenge_panel",
        "protocol": {
            "path": os.path.relpath(protocol_source, output),
            "sha256": _sha256(protocol_source),
        },
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_challenge_panel(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    if manifest.get("schema_version") != "1.0":
        errors.append("invalid_schema_version")
    if manifest.get("manifest_kind") != "diagnostic_challenge_panel":
        errors.append("invalid_manifest_kind")
    protocol_record = manifest.get("protocol")
    protocol: dict[str, Any] | None = None
    if not isinstance(protocol_record, Mapping):
        errors.append("missing_protocol")
    else:
        protocol_path = (path.parent / str(protocol_record.get("path", ""))).resolve()
        if not protocol_path.is_file():
            errors.append("missing_protocol")
        elif _sha256(protocol_path) != protocol_record.get("sha256"):
            errors.append("protocol_hash_mismatch")
        else:
            try:
                protocol = load_challenge_protocol(protocol_path)
            except ValueError as exc:
                errors.append(f"invalid_protocol:{exc}")
    records = manifest.get("outputs")
    seen: set[str] = set()
    if not isinstance(records, list):
        errors.append("outputs_not_list")
        records = []
    for record in records:
        if not isinstance(record, Mapping):
            errors.append("invalid_output_record")
            continue
        name = str(record.get("path", ""))
        target = path.parent / name
        if name in seen:
            errors.append(f"duplicate_output:{name}")
        seen.add(name)
        if not target.is_file():
            errors.append(f"missing_output:{name}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
    if seen != set(OUTPUT_NAMES):
        errors.append("output_set_mismatch")
    rows = ()
    results_path = path.parent / "raw_results.jsonl"
    if results_path.is_file():
        try:
            rows = load_jsonl_results(results_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("invalid_results")
    run_ids: set[str] = set()
    for row in rows:
        if row.run_id in run_ids:
            errors.append(f"duplicate_run_id:{row.run_id}")
        run_ids.add(row.run_id)
        if row.track not in HEADLINE_METHODS:
            errors.append(f"invalid_track:{row.run_id}")
        if row.status != "completed":
            errors.append(f"incomplete_row:{row.run_id}")
        if row.metadata.get("cohort") != "diagnostic_challenge":
            errors.append(f"invalid_cohort:{row.run_id}")
        if row.metadata.get("independent_block") != row.case_id:
            errors.append(f"invalid_block:{row.run_id}")
    if protocol is not None:
        expected_cases = {
            track: {str(item["case_id"]) for item in protocol["cases"][track]}
            for track in HEADLINE_METHODS
        }
        for track, methods in HEADLINE_METHODS.items():
            for method in methods:
                observed = {
                    row.case_id for row in rows
                    if row.track == track and row.method_id == method and row.status == "completed"
                }
                if observed != expected_cases[track]:
                    errors.append(f"coverage_mismatch:{track}:{method}")
    summary_path = path.parent / "summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append("invalid_summary")
        else:
            if summary.get("case_counts") != {"procurement": 4, "trading": 5}:
                errors.append("summary_case_count_mismatch")
            if summary.get("pair_counts") != {"procurement": 15, "trading": 10}:
                errors.append("summary_pair_count_mismatch")
            if protocol is not None and rows:
                try:
                    recomputed, _ = _summarize(
                        tuple(rows), float(protocol["practical_tolerance"])
                    )
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                    errors.append(f"summary_recomputation_failed:{exc}")
                else:
                    semantic_keys = (
                        "case_counts",
                        "headline_method_counts",
                        "pair_counts",
                        "separated_case_relations",
                        "separable_pair_counts",
                        "case_resolution",
                        "strongest_cases",
                        "practical_tolerance",
                    )
                    if any(summary.get(key) != recomputed.get(key) for key in semantic_keys):
                        errors.append("summary_separation_mismatch")
    return {"valid": not errors, "errors": errors, "result_rows": len(rows)}


__all__ = [
    "HEADLINE_METHODS",
    "build_challenge_panel",
    "load_challenge_protocol",
    "make_challenge_cases",
    "verify_challenge_panel",
]
