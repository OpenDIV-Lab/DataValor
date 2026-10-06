"""Deterministic tables and dependency-free SVG figures for the KDD paper."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

import yaml

from .catalog import load_catalog
from .heldout_evidence import (
    ECONOMIC_OBSERVABLE_SEMANTICS,
    economic_observable_errors,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUTS = {
    "target": PACKAGE_ROOT / "catalog" / "kdd_submission.yaml",
    "catalog": PACKAGE_ROOT / "catalog" / "mechanisms.yaml",
    "raw_results": PACKAGE_ROOT / "outputs" / "kdd_heldout_confirmatory" / "raw_results.jsonl",
    "contrasts": PACKAGE_ROOT / "outputs" / "kdd_heldout_confirmatory" / "confirmatory_contrasts.json",
    "finite_incentives": PACKAGE_ROOT / "outputs" / "kdd_finite_incentives" / "audit_results.json",
    "direct_market_transfer": PACKAGE_ROOT / "outputs" / "kdd_direct_market_transfer" / "transfer_contrasts.csv",
    "replication_comparisons": PACKAGE_ROOT / "outputs" / "kdd_heldout_replication_v2" / "replication_comparisons.json",
    "heldout_v1": PACKAGE_ROOT / "evidence" / "kdd_heldout_confirmatory_v1.json",
    "heldout_v2": PACKAGE_ROOT / "evidence" / "kdd_heldout_replication_v2.json",
    "qualification_decomposition": (
        PACKAGE_ROOT
        / "outputs"
        / "kdd_qualification_analysis"
        / "method_failure_decomposition.csv"
    ),
}
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "outputs" / "kdd_paper"
TABLES = (
    "table_scope_fidelity.csv",
    "table_confirmatory_contrasts.csv",
    "table_constraint_profiles.csv",
    "table_finite_incentives.csv",
    "table_replication_wave.csv",
    "table_economic_observable_scope.csv",
    "table_qualification_decomposition.csv",
)
FIGURES = (
    "figure_replication_multiconstruct.svg",
    "figure_procurement_concentration.svg",
    "figure_trading_thickness.svg",
    "figure_confirmatory_forest.svg",
    "figure_direct_market_transfer.svg",
    "figure_benchmark_contract.svg",
)
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9")
ECONOMIC_CLAIMS = (
    "task_utility",
    "proxy_calibration",
    "listing_ask",
    "transaction_price",
    "reservation_value",
    "buyer_value",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _metric(row: Mapping[str, Any], name: str) -> Any:
    metric = row.get("metrics", {}).get(name)
    if not isinstance(metric, Mapping):
        raise ValueError(f"missing required metric {name} for {row.get('method_id')}")
    if metric.get("applicable") is not True or metric.get("value") is None:
        raise ValueError(f"required metric {name} is not applicable for {row.get('method_id')}")
    return metric["value"]


def _optional_metric(row: Mapping[str, Any], name: str) -> Any | None:
    metric = row.get("metrics", {}).get(name)
    if not isinstance(metric, Mapping):
        raise ValueError(f"missing required metric {name} for {row.get('method_id')}")
    if metric.get("applicable") is not True or metric.get("value") is None:
        if not metric.get("reason"):
            raise ValueError(f"non-applicable metric {name} requires a reason for {row.get('method_id')}")
        return None
    _number(metric["value"], name)
    return metric["value"]


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = _number(value, "table value")
        if number == 0:
            return "0"
        return format(number, ".12g")
    return str(value)


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _format_number(row.get(column, "")) for column in columns})
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _load_inputs(
    inputs: Mapping[str, str | Path],
) -> tuple[
    dict[str, Path],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, str]],
    list[dict[str, Any]],
]:
    missing_keys = set(DEFAULT_INPUTS) - set(inputs)
    if missing_keys:
        raise ValueError(f"missing paper input keys: {sorted(missing_keys)}")
    paths = {key: Path(inputs[key]) for key in DEFAULT_INPUTS}
    for key, path in paths.items():
        if not path.is_file():
            raise ValueError(f"missing paper input {key}: {path}")
    target = yaml.safe_load(paths["target"].read_text(encoding="utf-8")) or {}
    catalog = load_catalog(paths["catalog"])
    raw = [
        json.loads(line)
        for line in paths["raw_results"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contrasts = json.loads(paths["contrasts"].read_text(encoding="utf-8"))
    incentives = json.loads(paths["finite_incentives"].read_text(encoding="utf-8"))
    with paths["direct_market_transfer"].open(encoding="utf-8", newline="") as handle:
        direct_transfer = list(csv.DictReader(handle))
    replication = json.loads(paths["replication_comparisons"].read_text(encoding="utf-8"))
    if not isinstance(contrasts, list):
        raise ValueError("confirmatory contrasts must be a list")
    if not isinstance(replication, list):
        raise ValueError("replication comparisons must be a list")
    return paths, target, catalog, raw, contrasts, incentives, direct_transfer, replication


def _replication_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expected = {
        "V-BANZHAF-vs-SHAPLEY": "valuation",
        "V-RVSV-vs-VSV": "valuation",
        "P-CGLR-vs-GPS": "procurement",
        "P-JTDEOM-vs-GPS": "procurement",
        "T-MCAFEE-vs-TR": "trading",
        "T-SBBA-vs-TR": "trading",
    }
    if len(rows) != len(expected):
        raise ValueError("replication table requires exactly six frozen contrasts")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        contrast_id = str(raw.get("contrast_id", ""))
        if contrast_id not in expected or contrast_id in seen:
            raise ValueError(f"invalid or duplicate replication contrast: {contrast_id}")
        seen.add(contrast_id)
        track = str(raw.get("track", ""))
        if track != expected[contrast_id]:
            raise ValueError(f"replication track mismatch: {contrast_id}")
        v1_blocks = int(_number(raw.get("v1_blocks"), "v1_blocks"))
        v2_blocks = int(_number(raw.get("v2_blocks"), "v2_blocks"))
        if v1_blocks < 3 or v2_blocks < 2:
            raise ValueError(f"insufficient replication blocks: {contrast_id}")
        parsed.append({
            "track": track,
            "contrast_id": contrast_id,
            "v1_effect": _number(raw.get("v1_effect"), "v1_effect"),
            "v1_ci_low": _number(raw.get("v1_ci_low"), "v1_ci_low"),
            "v1_ci_high": _number(raw.get("v1_ci_high"), "v1_ci_high"),
            "v1_decision": str(raw.get("v1_decision", "")),
            "v1_blocks": v1_blocks,
            "v2_effect": _number(raw.get("v2_effect"), "v2_effect"),
            "v2_ci_low": _number(raw.get("v2_ci_low"), "v2_ci_low"),
            "v2_ci_high": _number(raw.get("v2_ci_high"), "v2_ci_high"),
            "v2_decision": str(raw.get("v2_decision", "")),
            "v2_blocks": v2_blocks,
            "direction_category": str(raw.get("direction_category", "")),
            "interval_relation": str(raw.get("interval_relation", "")),
            "replication_verdict": str(raw.get("replication_verdict", "")),
            "pooled_inference": False,
        })
    return sorted(parsed, key=lambda row: (str(row["track"]), str(row["contrast_id"])))


def _economic_scope_rows(
    manifests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    tracks = ("procurement", "trading", "valuation")
    semantic_counts = {
        track: {semantic: 0 for semantic in ECONOMIC_OBSERVABLE_SEMANTICS}
        for track in tracks
    }
    claim_counts = {
        track: {claim: 0 for claim in ECONOMIC_CLAIMS} for track in tracks
    }
    source_uris = {track: set() for track in tracks}
    license_ids = {track: set() for track in tracks}
    block_ids = {track: set() for track in tracks}
    for manifest_index, manifest in enumerate(manifests):
        manifest_tracks = manifest.get("tracks")
        if not isinstance(manifest_tracks, Mapping):
            raise ValueError(
                f"held-out manifest {manifest_index} requires a tracks mapping"
            )
        for track in tracks:
            track_record = manifest_tracks.get(track)
            blocks = (
                track_record.get("blocks")
                if isinstance(track_record, Mapping)
                else None
            )
            if not isinstance(blocks, list) or not blocks:
                raise ValueError(
                    f"held-out manifest {manifest_index} requires {track} blocks"
                )
            for block_index, block in enumerate(blocks):
                if not isinstance(block, Mapping):
                    raise ValueError(
                        f"held-out {track} block {block_index} must be an object"
                    )
                block_id = str(block.get("block_id", "")).strip()
                if not block_id or block_id in block_ids[track]:
                    raise ValueError(
                        f"missing or duplicate held-out block ID: {track}/{block_id}"
                    )
                source_uri = str(block.get("source_uri", "")).strip()
                license_id = str(block.get("license_id", "")).strip()
                if not source_uri or not license_id:
                    raise ValueError(
                        f"held-out block requires source URI and license: {block_id}"
                    )
                observable = block.get("economic_observable")
                observable_errors = economic_observable_errors(
                    observable, f"{track}/{block_id}"
                )
                if observable_errors:
                    raise ValueError(
                        "invalid held-out economic observable: "
                        + ";".join(observable_errors)
                    )
                assert isinstance(observable, Mapping)
                semantic = str(observable["semantic"])
                semantic_counts[track][semantic] += 1
                for claim in observable["claims_supported"]:
                    claim_counts[track][str(claim)] += 1
                block_ids[track].add(block_id)
                source_uris[track].add(source_uri)
                license_ids[track].add(license_id)

    def row_for(track: str) -> dict[str, Any]:
        return {
            "track": track,
            "total_blocks": sum(semantic_counts[track].values()),
            **semantic_counts[track],
            **{
                f"{claim}_claims": count
                for claim, count in claim_counts[track].items()
            },
            "unique_source_uris": len(source_uris[track]),
            "license_ids": ";".join(sorted(license_ids[track])),
        }

    rows = [row_for(track) for track in tracks]
    rows.append(
        {
            "track": "all",
            "total_blocks": sum(row["total_blocks"] for row in rows),
            **{
                semantic: sum(semantic_counts[track][semantic] for track in tracks)
                for semantic in ECONOMIC_OBSERVABLE_SEMANTICS
            },
            **{
                f"{claim}_claims": sum(
                    claim_counts[track][claim] for track in tracks
                )
                for claim in ECONOMIC_CLAIMS
            },
            "unique_source_uris": len(set().union(*source_uris.values())),
            "license_ids": ";".join(
                sorted(set().union(*license_ids.values()))
            ),
        }
    )
    return rows


def _direct_transfer_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expected_contrasts = {
        "P-CGLR-vs-GPS": ("cgl_randomized", "generalized_proportional_share"),
        "P-JTDEOM-vs-GPS": ("jt_deterministic_eom", "generalized_proportional_share"),
    }
    expected_scope = "descriptive_support_transfer_not_population_inference"
    allowed_price_modes = {"subscription", "one-off", "usage-based"}
    if len(rows) != 16:
        raise ValueError("direct-market transfer requires exactly 16 rows (2 contrasts by 8 cohorts)")

    parsed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    cohorts_by_contrast: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        contrast_id = str(row.get("contrast_id", ""))
        cohort_id = str(row.get("cohort_id", ""))
        if contrast_id not in expected_contrasts:
            raise ValueError(f"invalid direct-market contrast: {contrast_id}")
        key = (contrast_id, cohort_id)
        if key in seen:
            raise ValueError(f"duplicate direct-market transfer row: {contrast_id}/{cohort_id}")
        seen.add(key)
        expected_a, expected_b = expected_contrasts[contrast_id]
        if (row.get("method_a"), row.get("method_b")) != (expected_a, expected_b):
            raise ValueError(f"invalid methods for direct-market contrast: {contrast_id}")
        if row.get("comparison_scope") != expected_scope:
            raise ValueError(f"invalid direct-market comparison scope: {row.get('comparison_scope')}")
        price_mode = str(row.get("price_mode", ""))
        if price_mode not in allowed_price_modes:
            raise ValueError(f"invalid direct-market price mode: {price_mode}")
        effect = _number(row.get("direct_effect"), "direct_effect")
        chile_min = _number(row.get("chile_effect_min"), "chile_effect_min")
        chile_max = _number(row.get("chile_effect_max"), "chile_effect_max")
        if chile_min > chile_max:
            raise ValueError(f"invalid ChileCompra effect range for {contrast_id}/{cohort_id}")
        outside = str(row.get("outside_chile_range", "")).lower()
        if outside not in {"true", "false"}:
            raise ValueError(f"invalid outside_chile_range for {contrast_id}/{cohort_id}")
        platform = str(row.get("platform", "")).strip()
        if not cohort_id or not platform:
            raise ValueError("direct-market cohort_id and platform must be non-empty")
        cohorts_by_contrast[contrast_id].add(cohort_id)
        parsed.append(
            {
                "contrast_id": contrast_id,
                "cohort_id": cohort_id,
                "platform": platform,
                "price_mode": price_mode,
                "direct_effect": effect,
                "chile_effect_min": chile_min,
                "chile_effect_max": chile_max,
            }
        )
    if set(cohorts_by_contrast) != set(expected_contrasts):
        raise ValueError("direct-market transfer must cover both registered contrasts")
    cohort_sets = list(cohorts_by_contrast.values())
    if any(len(cohorts) != 8 for cohorts in cohort_sets) or cohort_sets[0] != cohort_sets[1]:
        raise ValueError("direct-market transfer requires the same 8 cohorts for both contrasts")
    return sorted(parsed, key=lambda row: (row["contrast_id"], row["cohort_id"]))


def _scope_rows(target: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    rows: list[dict[str, Any]] = []
    headline: dict[str, list[str]] = {}
    flagships = target.get("flagships", {})
    parity = target.get("parity_evidence", {})
    for track in ("valuation", "procurement", "trading"):
        section = flagships.get(track, {})
        methods = [str(item) for item in section.get("method_ids", ())]
        if not methods:
            raise ValueError(f"missing headline methods for {track}")
        headline[track] = methods
        for method_id in methods:
            if method_id not in catalog:
                raise ValueError(f"headline method missing from catalog: {method_id}")
            source = catalog[method_id]
            parity_record = parity.get(method_id, {})
            rows.append(
                {
                    "track": track,
                    "setting_id": section.get("setting_id", ""),
                    "structural_axis": section.get("structural_axis", ""),
                    "method_id": method_id,
                    "provenance_kind": source.get("provenance_kind", ""),
                    "source": source.get("source", ""),
                    "reference_url": source.get("reference_url", ""),
                    "reference_keys": ";".join(source.get("reference_keys", ())),
                    "algorithm_location": source.get("algorithm_location", ""),
                    "deviations": ";".join(source.get("deviations", ())),
                    "parity_status": parity_record.get("status", "missing"),
                    "parity_paths": ";".join(parity_record.get("paths", ())),
                }
            )
    return rows, headline


def _validate_and_select_raw(raw: Sequence[Mapping[str, Any]], headline: Mapping[str, Sequence[str]]) -> list[dict[str, Any]]:
    completed = [dict(row) for row in raw if row.get("status") == "completed"]
    required_metrics = {
        "valuation": ("replication_factor", "topk_test_utility"),
        "procurement": (
            "largest_singleton_share",
            "oracle_ratio",
        ),
        "trading": (
            "efficient_trade_count",
            "gain_from_trade_ratio",
        ),
    }
    selected: list[dict[str, Any]] = []
    for track in ("valuation", "procurement", "trading"):
        track_methods = set(headline[track])
        track_rows = [row for row in completed if row.get("track") == track and row.get("method_id") in track_methods]
        observed = {str(row.get("method_id")) for row in track_rows}
        missing = sorted(track_methods - observed)
        if missing:
            raise ValueError(f"missing headline results for {track}: {', '.join(missing)}")
        blocks = {str(row.get("metadata", {}).get("independent_block", "")) for row in track_rows}
        blocks.discard("")
        if len(blocks) < 3:
            raise ValueError(f"{track} requires at least 3 independent blocks")
        for row in track_rows:
            for name in required_metrics[track]:
                if name == "replication_factor":
                    value = row.get("metadata", {}).get(name)
                    if value is None:
                        raise ValueError(f"missing required metric {name} for {row.get('method_id')}")
                    _number(value, name)
                else:
                    _metric(row, name)
            if track == "valuation":
                for name in (
                    "replication_owner_rank_change",
                    "replication_reward_share_gain",
                    "replication_score_inflation_ratio",
                ):
                    _optional_metric(row, name)
            elif track == "procurement":
                for name in ("budget_violation", "seller_ir_violation_count"):
                    _optional_metric(row, name)
            else:
                for name in ("individual_rationality", "weak_budget_balance"):
                    _optional_metric(row, name)
        selected.extend(track_rows)
    return sorted(selected, key=lambda row: (row["track"], row["method_id"], row["case_id"], row["seed"]))


def _contrast_rows(contrasts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_tracks: set[str] = set()
    for contrast in contrasts:
        decision = str(contrast.get("decision", ""))
        if decision not in {"confirmed", "boundary", "discrepant", "not_auditable"}:
            raise ValueError(f"invalid contrast decision: {decision}")
        blocks = int(contrast.get("independent_blocks", 0))
        if blocks < 3 or contrast.get("missing_blocks"):
            raise ValueError(f"contrast {contrast.get('contrast_id')} is not auditable on 3 complete blocks")
        track = str(contrast.get("track", ""))
        if track not in {"valuation", "procurement", "trading"}:
            raise ValueError(f"invalid contrast track: {track}")
        seen_tracks.add(track)
        for field in ("effect", "ci_low", "ci_high", "holm_adjusted_p_value", "worst_block_effect"):
            _number(contrast.get(field), field)
        rows.append(
            {
                "track": track,
                "contrast_id": contrast.get("contrast_id"),
                "effect": contrast.get("effect"),
                "ci_low": contrast.get("ci_low"),
                "ci_high": contrast.get("ci_high"),
                "raw_p_value": contrast.get("raw_p_value"),
                "holm_adjusted_p_value": contrast.get("holm_adjusted_p_value"),
                "independent_blocks": blocks,
                "case_count": contrast.get("case_count"),
                "run_count": contrast.get("run_count"),
                "sign_consistency": contrast.get("sign_consistency"),
                "decision": decision,
                "worst_block": contrast.get("worst_block"),
                "worst_block_effect": contrast.get("worst_block_effect"),
            }
        )
    if seen_tracks != {"valuation", "procurement", "trading"}:
        raise ValueError("contrasts must cover valuation, procurement, and trading")
    return sorted(rows, key=lambda row: (row["track"], row["contrast_id"]))


def _profile_rows(raw: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in raw:
        groups[(str(row["track"]), str(row["method_id"]))].append(row)
    specs = {
        "valuation": ("topk_test_utility", "replication_reward_share_gain", "replication_score_inflation_ratio"),
        "procurement": ("oracle_ratio", "budget_violation", "seller_ir_violation_count"),
        "trading": ("gain_from_trade_ratio", "individual_rationality", "weak_budget_balance"),
    }
    rows: list[dict[str, Any]] = []
    for (track, method_id), items in sorted(groups.items()):
        primary, guardrail_1, guardrail_2 = specs[track]
        primary_values = [_number(_metric(item, primary), primary) for item in items]
        first_observed = [_optional_metric(item, guardrail_1) for item in items]
        second_observed = [_optional_metric(item, guardrail_2) for item in items]
        first_values = [_number(value, guardrail_1) for value in first_observed if value is not None]
        second_values = [_number(value, guardrail_2) for value in second_observed if value is not None]
        if not first_values or not second_values:
            raise ValueError(f"guardrail metrics have no applicable values for {method_id}")
        if track == "trading":
            first_values = [1.0 - value for value in first_values]
            second_values = [1.0 - value for value in second_values]
            guardrail_1 = "individual_rationality_failure"
            guardrail_2 = "weak_budget_balance_failure"
        rows.append(
            {
                "track": track,
                "method_id": method_id,
                "completed_runs": len(items),
                "independent_blocks": len({item["metadata"]["independent_block"] for item in items}),
                "primary_metric": primary,
                "primary_mean": fmean(primary_values),
                "primary_min": min(primary_values),
                "guardrail_1": guardrail_1,
                "guardrail_1_coverage": f"{len(first_values)}/{len(items)}",
                "guardrail_1_mean": fmean(first_values),
                "guardrail_1_max": max(first_values),
                "guardrail_2": guardrail_2,
                "guardrail_2_coverage": f"{len(second_values)}/{len(items)}",
                "guardrail_2_mean": fmean(second_values),
                "guardrail_2_max": max(second_values),
            }
        )
    return rows


def _incentive_rows(incentives: Mapping[str, Any]) -> list[dict[str, Any]]:
    if incentives.get("claim_strength") != "empirical_finite_domain_audit":
        raise ValueError("finite incentive input has invalid claim strength")
    rows = []
    for record in incentives.get("methods", ()):
        rows.append(
            {
                "track": record.get("track"),
                "method_id": record.get("method_id"),
                "estimand": record.get("estimand"),
                "expectation": record.get("expectation"),
                "expected_max_gain": record.get("expected_max_gain"),
                "profile_count": record.get("profile_count"),
                "seed_count": record.get("seed_count"),
                "deviation_evaluation_count": record.get("deviation_evaluation_count"),
                "max_gain": record.get("max_gain"),
                "profitable_deviation_count": record.get("profitable_deviation_count"),
                "conclusion": record.get("conclusion"),
                "report_domain_complete": record.get("report_domain_complete"),
                "random_support_complete": record.get("random_support_complete"),
            }
        )
    if not rows:
        raise ValueError("finite incentive input has no method records")
    return sorted(rows, key=lambda row: (row["track"], row["method_id"]))


def _qualification_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    required = {
        "method_id",
        "joint_status",
        "failed_requirements",
        "unauditable_requirements",
        "minimum_relaxation_count",
        "minimum_relaxation_requirements",
        "blocker_kinds",
        "analysis_role",
    }
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        missing = required - set(raw)
        if missing:
            raise ValueError(
                f"qualification decomposition missing columns: {sorted(missing)}"
            )
        method_id = str(raw["method_id"]).strip()
        if not method_id or method_id in seen:
            raise ValueError("qualification method IDs must be non-empty and unique")
        seen.add(method_id)
        status = str(raw["joint_status"])
        if status not in {"pass", "fail", "not_auditable"}:
            raise ValueError(f"invalid qualification joint status: {status}")
        role = str(raw["analysis_role"])
        if role != "diagnostic_not_official_rank":
            raise ValueError(f"invalid qualification analysis role: {role}")
        relaxation_count = int(raw["minimum_relaxation_count"])
        relaxation = tuple(
            item
            for item in str(raw["minimum_relaxation_requirements"]).split(";")
            if item
        )
        if relaxation_count != len(relaxation):
            raise ValueError(f"qualification relaxation count mismatch: {method_id}")
        parsed.append(
            {
                "method_id": method_id,
                "joint_status": status,
                "failed_requirements": raw["failed_requirements"],
                "unauditable_requirements": raw["unauditable_requirements"],
                "minimum_relaxation_count": relaxation_count,
                "minimum_relaxation_requirements": raw[
                    "minimum_relaxation_requirements"
                ],
                "blocker_kinds": raw["blocker_kinds"],
                "analysis_role": role,
            }
        )
    if not parsed:
        raise ValueError("qualification decomposition has no method records")
    return sorted(parsed, key=lambda row: str(row["method_id"]))


def _series_points(raw: Sequence[Mapping[str, Any]], track: str, x_name: str, y_name: str, *, metadata_x: bool = False) -> dict[str, list[tuple[float, float]]]:
    buckets: dict[tuple[str, float], list[float]] = defaultdict(list)
    for row in raw:
        if row["track"] != track:
            continue
        x_value = row["metadata"].get(x_name) if metadata_x else _metric(row, x_name)
        x = _number(x_value, x_name)
        y_value = _optional_metric(row, y_name)
        if y_value is None:
            continue
        y = _number(y_value, y_name)
        buckets[(str(row["method_id"]), x)].append(y)
    result: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (method, x), values in sorted(buckets.items()):
        result[method].append((x, fmean(values)))
    return dict(result)


def _svg_line_panels(title: str, description: str, panels: Sequence[tuple[str, str, str, Mapping[str, Sequence[tuple[float, float]]]]]) -> str:
    width, height = 960, 560
    two_columns = len(panels) > 1
    panel_width = 430 if two_columns else 820
    panel_height = 205 if len(panels) > 2 else 390
    positions = [(70, 80), (520, 80), (70, 330), (520, 330)] if two_columns else [(90, 90)]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f"<title>{html.escape(title)}</title>",
        f"<desc>{html.escape(description)}</desc>",
        '<rect width="960" height="560" fill="#ffffff"/>',
        f'<text x="480" y="32" text-anchor="middle" font-family="sans-serif" font-size="20">{html.escape(title)}</text>',
    ]
    for panel_index, ((panel_title, x_label, y_label, series), (left, top)) in enumerate(zip(panels, positions, strict=True)):
        plot_width = panel_width - 80
        plot_height = panel_height - 55
        all_points = [point for points in series.values() for point in points]
        if not all_points:
            raise ValueError(f"figure panel has no points: {panel_title}")
        xs = [point[0] for point in all_points]
        ys = [point[1] for point in all_points]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmin == xmax:
            xmin, xmax = xmin - 0.5, xmax + 0.5
        if ymin == ymax:
            ymin, ymax = ymin - 0.5, ymax + 0.5
        pad_y = (ymax - ymin) * 0.08
        ymin, ymax = ymin - pad_y, ymax + pad_y
        x0, y0 = left + 55, top + plot_height
        parts.extend(
            [
                f'<text x="{left + panel_width / 2:.2f}" y="{top - 12}" text-anchor="middle" font-family="sans-serif" font-size="13">{html.escape(panel_title)}</text>',
                f'<line x1="{x0}" y1="{top}" x2="{x0}" y2="{y0}" stroke="#333"/>',
                f'<line x1="{x0}" y1="{y0}" x2="{x0 + plot_width}" y2="{y0}" stroke="#333"/>',
                f'<text x="{x0 + plot_width / 2:.2f}" y="{y0 + 35}" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(x_label)}</text>',
                f'<text x="{left + 8}" y="{top + plot_height / 2:.2f}" transform="rotate(-90 {left + 8} {top + plot_height / 2:.2f})" text-anchor="middle" font-family="sans-serif" font-size="11">{html.escape(y_label)}</text>',
            ]
        )
        for series_index, (label, points) in enumerate(sorted(series.items())):
            color = PALETTE[series_index % len(PALETTE)]
            coords = []
            for x, y in sorted(points):
                px = x0 + (x - xmin) / (xmax - xmin) * plot_width
                py = top + (ymax - y) / (ymax - ymin) * plot_height
                coords.append(f"{px:.2f},{py:.2f}")
            parts.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2"/>')
            for coord in coords:
                px, py = coord.split(",")
                parts.append(f'<circle cx="{px}" cy="{py}" r="3" fill="{color}"/>')
            legend_x = left + 62 + (series_index % 3) * 120
            legend_y = top + plot_height + 52 + (series_index // 3) * 13
            parts.append(f'<text x="{legend_x}" y="{legend_y}" font-family="sans-serif" font-size="9" fill="{color}">{html.escape(label)}</text>')
        parts.append(f'<text x="{x0}" y="{y0 + 14}" font-family="sans-serif" font-size="9">{xmin:.3g}</text>')
        parts.append(f'<text x="{x0 + plot_width}" y="{y0 + 14}" text-anchor="end" font-family="sans-serif" font-size="9">{xmax:.3g}</text>')
        parts.append(f'<text x="{x0 - 5}" y="{y0}" text-anchor="end" font-family="sans-serif" font-size="9">{ymin:.3g}</text>')
        parts.append(f'<text x="{x0 - 5}" y="{top + 8}" text-anchor="end" font-family="sans-serif" font-size="9">{ymax:.3g}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _svg_forest(contrasts: Sequence[Mapping[str, Any]]) -> str:
    values = [float(row[field]) for row in contrasts for field in ("ci_low", "ci_high")]
    low, high = min(values + [0.0]), max(values + [0.0])
    if low == high:
        low, high = low - 0.5, high + 0.5
    margin = (high - low) * 0.1
    low, high = low - margin, high + margin
    left, right, top, bottom = 260, 900, 75, 515

    def px(value: float) -> float:
        return left + (value - low) / (high - low) * (right - left)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">',
        "<title>Confirmatory contrast forest plot</title>",
        "<desc>Oriented effects and block-bootstrap 95 percent intervals for every frozen primary contrast.</desc>",
        '<rect width="960" height="560" fill="#ffffff"/>',
        '<text x="480" y="32" text-anchor="middle" font-family="sans-serif" font-size="20">Confirmatory effects with 95% intervals</text>',
        f'<line x1="{px(0):.2f}" y1="{top}" x2="{px(0):.2f}" y2="{bottom}" stroke="#777" stroke-dasharray="4 4"/>',
    ]
    spacing = (bottom - top) / max(1, len(contrasts))
    for index, row in enumerate(contrasts):
        y = top + spacing * (index + 0.5)
        color = PALETTE[("valuation", "procurement", "trading").index(str(row["track"]))]
        parts.extend(
            [
                f'<text x="245" y="{y + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11">{html.escape(str(row["contrast_id"]))}</text>',
                f'<line x1="{px(float(row["ci_low"])):.2f}" y1="{y:.2f}" x2="{px(float(row["ci_high"])):.2f}" y2="{y:.2f}" stroke="{color}" stroke-width="3"/>',
                f'<circle cx="{px(float(row["effect"])):.2f}" cy="{y:.2f}" r="5" fill="{color}"/>',
            ]
        )
    parts.extend(
        [
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#333"/>',
            f'<text x="{left}" y="{bottom + 18}" font-family="sans-serif" font-size="10">{low:.3g}</text>',
            f'<text x="{right}" y="{bottom + 18}" text-anchor="end" font-family="sans-serif" font-size="10">{high:.3g}</text>',
            '<text x="580" y="550" text-anchor="middle" font-family="sans-serif" font-size="11">oriented effect (positive favors the pre-registered hypothesis)</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def _svg_direct_market_transfer(rows: Sequence[Mapping[str, Any]]) -> str:
    contrast_labels = {
        "P-CGLR-vs-GPS": "CGL-R − GPS",
        "P-JTDEOM-vs-GPS": "JT-DEOM − GPS",
    }
    mode_colors = {
        "subscription": "#0072B2",
        "one-off": "#D55E00",
        "usage-based": "#009E73",
    }
    platform_labels = {
        "AWS Data Exchange": "AWS",
        "Beijing International Data Exchange": "Beijing",
        "Datarade": "Datarade",
        "Snowflake Marketplace": "Snowflake",
        "Zhejiang Data Exchange": "Zhejiang",
        "Zhejiang Big Data Exchange": "Zhejiang",
    }
    mode_labels = {"subscription": "sub", "one-off": "one", "usage-based": "use"}
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["contrast_id"])].append(row)
    all_values = [0.0]
    for row in rows:
        all_values.extend(
            [float(row["direct_effect"]), float(row["chile_effect_min"]), float(row["chile_effect_max"])]
        )
    ymin, ymax = min(all_values), max(all_values)
    span = ymax - ymin
    if span == 0:
        span = 1.0
    ymin -= span * 0.12
    ymax += span * 0.12

    left, right = 125.0, 925.0
    plot_width = right - left
    panel_tops = (92.0, 318.0)
    plot_height = 148.0

    def py(value: float, top: float) -> float:
        return top + (ymax - value) / (ymax - ymin) * plot_height

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">',
        "<title>Direct data-market price-support transfer</title>",
        "<desc>Two panels compare procurement oracle-ratio effects relative to GPS across eight direct marketplace listing-price cohorts. Grey bands show ChileCompra block-effect ranges; colored points encode price modes. These cohorts are descriptive and do not support population inference.</desc>",
        '<rect width="960" height="560" fill="#ffffff"/>',
        '<text x="480" y="30" text-anchor="middle" font-family="sans-serif" font-size="20">Direct listing-price support transfer</text>',
        '<rect x="126" y="46" width="24" height="11" fill="#d9d9d9"/>',
        '<text x="157" y="56" font-family="sans-serif" font-size="10">ChileCompra block-effect range</text>',
    ]
    legend_x = 420
    for index, mode in enumerate(("subscription", "one-off", "usage-based")):
        x = legend_x + index * 145
        parts.append(f'<circle cx="{x}" cy="52" r="4" fill="{mode_colors[mode]}"/>')
        parts.append(
            f'<text x="{x + 9}" y="56" font-family="sans-serif" font-size="10">{html.escape(mode)}</text>'
        )

    for panel_index, contrast_id in enumerate(("P-CGLR-vs-GPS", "P-JTDEOM-vs-GPS")):
        top = panel_tops[panel_index]
        panel_rows = sorted(grouped[contrast_id], key=lambda row: str(row["cohort_id"]))
        chile_min = min(float(row["chile_effect_min"]) for row in panel_rows)
        chile_max = max(float(row["chile_effect_max"]) for row in panel_rows)
        band_top = py(chile_max, top)
        band_bottom = py(chile_min, top)
        zero_y = py(0.0, top)
        parts.extend(
            [
                f'<text x="{(left + right) / 2:.2f}" y="{top - 12:.2f}" text-anchor="middle" font-family="sans-serif" font-size="13">{contrast_labels[contrast_id]}</text>',
                f'<rect x="{left:.2f}" y="{band_top:.2f}" width="{plot_width:.2f}" height="{band_bottom - band_top:.2f}" fill="#d9d9d9"/>',
                f'<line x1="{left:.2f}" y1="{zero_y:.2f}" x2="{right:.2f}" y2="{zero_y:.2f}" stroke="#555" stroke-width="1.2" stroke-dasharray="5 4"/>',
                f'<line x1="{left:.2f}" y1="{top:.2f}" x2="{left:.2f}" y2="{top + plot_height:.2f}" stroke="#333"/>',
                f'<line x1="{left:.2f}" y1="{top + plot_height:.2f}" x2="{right:.2f}" y2="{top + plot_height:.2f}" stroke="#333"/>',
                f'<text x="38" y="{top + 12:.2f}" text-anchor="start" font-family="sans-serif" font-size="9">effect vs GPS</text>',
                f'<text x="{left - 8:.2f}" y="{py(ymax, top) + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="9">{ymax:.3g}</text>',
                f'<text x="{left - 8:.2f}" y="{zero_y + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="9">0</text>',
                f'<text x="{left - 8:.2f}" y="{py(ymin, top) + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="9">{ymin:.3g}</text>',
            ]
        )
        for index, row in enumerate(panel_rows):
            x = left + (index + 0.5) * plot_width / len(panel_rows)
            y = py(float(row["direct_effect"]), top)
            mode = str(row["price_mode"])
            platform = platform_labels.get(str(row["platform"]), str(row["platform"]))
            label = f"{platform}-{mode_labels[mode]}"
            label_y = top + plot_height + 12 + (index % 2) * 11
            parts.extend(
                [
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{mode_colors[mode]}" stroke="#ffffff" stroke-width="1"/>',
                    f'<text x="{x:.2f}" y="{label_y:.2f}" text-anchor="middle" font-family="sans-serif" font-size="7.5">{html.escape(label)}</text>',
                ]
            )
    parts.extend(
        [
            '<text x="480" y="548" text-anchor="middle" font-family="sans-serif" font-size="10">Exploratory support transfer: listed asks are not transactions or private costs.</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def _svg_benchmark_contract(
    scope_rows: Sequence[Mapping[str, Any]],
    headline: Mapping[str, Sequence[str]],
    raw: Sequence[Mapping[str, Any]],
) -> str:
    track_specs = {
        "valuation": (
            "Valuation",
            "owner replication",
            "utility | rank | reward share | score inflation",
            "#0072B2",
        ),
        "procurement": (
            "Procurement",
            "seller concentration",
            "oracle ratio | budget | payments | seller IR",
            "#D55E00",
        ),
        "trading": (
            "Trading",
            "market thickness",
            "GFT | trade count | buyer/seller IR | WBB",
            "#009E73",
        ),
    }
    blocks_by_track: dict[str, set[str]] = defaultdict(set)
    for row in raw:
        block = str(row.get("metadata", {}).get("independent_block", ""))
        if block:
            blocks_by_track[str(row["track"])].add(block)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">',
        "<title>DataMechBench evaluation contract and evidence flow</title>",
        "<desc>Source-linked mechanisms, separated case banks, and evaluator-held types feed a mechanism profile containing score, allocation, and payment. Three track-specific evaluations produce constraint-qualified profiles, claim-aligned block inference, and explicit evidence limits without a cross-track composite rank.</desc>",
        '<rect width="960" height="560" fill="#ffffff"/>',
        '<text x="480" y="31" text-anchor="middle" font-family="sans-serif" font-size="20">DataMechBench: mechanism evaluation, not a scalar leaderboard</text>',
        '<text x="480" y="52" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#555555">Inputs and information boundaries → mechanism outcomes → track-specific evidence</text>',
    ]

    input_boxes = (
        ("Source-linked mechanisms", f"{len(scope_rows)} scoped families · parity · provenance"),
        ("Separated case banks", "development choices ≠ held-out evidence"),
        ("Evaluator-held true types", "reports ≠ true costs or values"),
    )
    for index, (title, subtitle) in enumerate(input_boxes):
        y = 100 + index * 103
        parts.extend(
            [
                f'<rect x="28" y="{y}" width="225" height="70" rx="8" fill="#f2f2f2" stroke="#777777"/>',
                f'<text x="140.5" y="{y + 27}" text-anchor="middle" font-family="sans-serif" font-size="13" font-weight="bold">{html.escape(title)}</text>',
                f'<text x="140.5" y="{y + 49}" text-anchor="middle" font-family="sans-serif" font-size="9.5" fill="#444444">{html.escape(subtitle)}</text>',
                f'<line x1="253" y1="{y + 35}" x2="282" y2="{y + 35}" stroke="#666666" stroke-width="1.5"/>',
                f'<polygon class="flow-arrow" points="282,{y + 30} 292,{y + 35} 282,{y + 40}" fill="#666666"/>',
            ]
        )

    parts.extend(
        [
            '<rect x="300" y="86" width="320" height="103" rx="10" fill="#e8f2f8" stroke="#0072B2" stroke-width="1.5"/>',
            '<text x="460" y="113" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="bold">Mechanism profile</text>',
            '<text x="460" y="140" text-anchor="middle" font-family="sans-serif" font-size="14">(score, allocation, payment)</text>',
            '<text x="460" y="166" text-anchor="middle" font-family="sans-serif" font-size="9.5" fill="#333333">visible information stays distinct from evaluator-held state</text>',
        ]
    )
    for index, track in enumerate(("valuation", "procurement", "trading")):
        label, axis, metrics, color = track_specs[track]
        count = len(headline[track])
        family_word = "family" if count == 1 else "families"
        block_count = len(blocks_by_track[track])
        y = 215 + index * 82
        parts.extend(
            [
                f'<rect x="300" y="{y}" width="320" height="65" rx="8" fill="#ffffff" stroke="{color}" stroke-width="1.5"/>',
                f'<rect x="300" y="{y}" width="9" height="65" rx="4" fill="{color}"/>',
                f'<text x="324" y="{y + 21}" font-family="sans-serif" font-size="12.5" font-weight="bold">{label}: {count} {family_word}</text>',
                f'<text x="600" y="{y + 21}" text-anchor="end" font-family="sans-serif" font-size="9.5" fill="#444444">{block_count} held-out blocks</text>',
                f'<text x="324" y="{y + 40}" font-family="sans-serif" font-size="9.5">axis: {html.escape(axis)}</text>',
                f'<text x="324" y="{y + 56}" font-family="sans-serif" font-size="8.5" fill="#444444">{html.escape(metrics)}</text>',
            ]
        )

    output_boxes = (
        ("Constraint-qualified profiles", "performance beside feasibility / IR / WBB"),
        ("Claim-aligned statistics", "case aggregation → source-block effect + CI"),
        ("Explicit evidence limits", "confirmed | boundary | discrepant | not auditable"),
    )
    for index, (title, subtitle) in enumerate(output_boxes):
        y = 112 + index * 116
        parts.extend(
            [
                f'<line x1="620" y1="{y + 34}" x2="649" y2="{y + 34}" stroke="#666666" stroke-width="1.5"/>',
                f'<polygon class="flow-arrow" points="649,{y + 29} 659,{y + 34} 649,{y + 39}" fill="#666666"/>',
                f'<rect x="667" y="{y}" width="265" height="68" rx="8" fill="#f8f4e8" stroke="#8C6D1F"/>',
                f'<text x="799.5" y="{y + 26}" text-anchor="middle" font-family="sans-serif" font-size="12.5" font-weight="bold">{html.escape(title)}</text>',
                f'<text x="799.5" y="{y + 48}" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#444444">{html.escape(subtitle)}</text>',
            ]
        )
    parts.extend(
        [
            '<rect x="667" y="470" width="265" height="48" rx="8" fill="#f7e7e7" stroke="#A33A3A"/>',
            '<text x="799.5" y="499" text-anchor="middle" font-family="sans-serif" font-size="12.5" font-weight="bold" fill="#7A2020">No cross-track composite rank</text>',
            '<text x="480" y="548" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#333333">Every result retains source fidelity, applicability, guardrail coverage, and evidence scope.</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def build_kdd_paper_artifacts(
    inputs: Mapping[str, str | Path] = DEFAULT_INPUTS,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    paths, target, catalog, raw, contrasts, incentives, direct_transfer, replication = _load_inputs(inputs)
    scope_rows, headline = _scope_rows(target, catalog)
    selected_raw = _validate_and_select_raw(raw, headline)
    contrast_rows = _contrast_rows(contrasts)
    profile_rows = _profile_rows(selected_raw)
    incentive_rows = _incentive_rows(incentives)
    direct_transfer_rows = _direct_transfer_rows(direct_transfer)
    replication_rows = _replication_rows(replication)
    heldout_manifests = [
        json.loads(paths[key].read_text(encoding="utf-8"))
        for key in ("heldout_v1", "heldout_v2")
    ]
    economic_scope_rows = _economic_scope_rows(heldout_manifests)
    with paths["qualification_decomposition"].open(
        encoding="utf-8", newline=""
    ) as handle:
        qualification_rows = _qualification_rows(list(csv.DictReader(handle)))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output / TABLES[0],
        ("track", "setting_id", "structural_axis", "method_id", "provenance_kind", "source", "reference_url", "reference_keys", "algorithm_location", "deviations", "parity_status", "parity_paths"),
        scope_rows,
    )
    _write_csv(
        output / TABLES[1],
        ("track", "contrast_id", "effect", "ci_low", "ci_high", "raw_p_value", "holm_adjusted_p_value", "independent_blocks", "case_count", "run_count", "sign_consistency", "decision", "worst_block", "worst_block_effect"),
        contrast_rows,
    )
    _write_csv(
        output / TABLES[2],
        ("track", "method_id", "completed_runs", "independent_blocks", "primary_metric", "primary_mean", "primary_min", "guardrail_1", "guardrail_1_coverage", "guardrail_1_mean", "guardrail_1_max", "guardrail_2", "guardrail_2_coverage", "guardrail_2_mean", "guardrail_2_max"),
        profile_rows,
    )
    _write_csv(
        output / TABLES[3],
        ("track", "method_id", "estimand", "expectation", "expected_max_gain", "profile_count", "seed_count", "deviation_evaluation_count", "max_gain", "profitable_deviation_count", "conclusion", "report_domain_complete", "random_support_complete"),
        incentive_rows,
    )
    _write_csv(
        output / TABLES[4],
        ("track", "contrast_id", "v1_effect", "v1_ci_low", "v1_ci_high", "v1_decision", "v1_blocks", "v2_effect", "v2_ci_low", "v2_ci_high", "v2_decision", "v2_blocks", "direction_category", "interval_relation", "replication_verdict", "pooled_inference"),
        replication_rows,
    )
    _write_csv(
        output / TABLES[5],
        (
            "track",
            "total_blocks",
            "task_utility",
            "proxy",
            "listing_ask",
            "settlement",
            "elicited_reservation",
            "task_utility_claims",
            "proxy_calibration_claims",
            "listing_ask_claims",
            "transaction_price_claims",
            "reservation_value_claims",
            "buyer_value_claims",
            "unique_source_uris",
            "license_ids",
        ),
        economic_scope_rows,
    )
    _write_csv(
        output / TABLES[6],
        (
            "method_id",
            "joint_status",
            "failed_requirements",
            "unauditable_requirements",
            "minimum_relaxation_count",
            "minimum_relaxation_requirements",
            "blocker_kinds",
            "analysis_role",
        ),
        qualification_rows,
    )
    replication_panels = []
    for title, metric, label in (
        ("Owner rank displacement", "replication_owner_rank_change", "rank change"),
        ("Replicated-owner reward share", "replication_reward_share_gain", "share gain"),
        ("Score inflation", "replication_score_inflation_ratio", "inflation ratio"),
        ("Downstream top-k utility", "topk_test_utility", "test utility"),
    ):
        replication_panels.append(
            (title, "replication factor", label, _series_points(selected_raw, "valuation", "replication_factor", metric, metadata_x=True))
        )
    (output / FIGURES[0]).write_text(
        _svg_line_panels(
            "Replication robustness is multi-construct",
            "Held-out method means for owner rank, reward share, score inflation, and downstream utility by exact bundle replication factor.",
            replication_panels,
        ),
        encoding="utf-8",
    )
    (output / FIGURES[1]).write_text(
        _svg_line_panels(
            "Procurement performance under concentration",
            "Held-out oracle utility ratio against the largest-singleton share, averaged within method and structural-axis value.",
            [("Oracle ratio", "largest-singleton share", "oracle ratio", _series_points(selected_raw, "procurement", "largest_singleton_share", "oracle_ratio"))],
        ),
        encoding="utf-8",
    )
    (output / FIGURES[2]).write_text(
        _svg_line_panels(
            "Trading performance under market thickness",
            "Held-out gain-from-trade ratio against efficient trade count, averaged within method and thickness value.",
            [("GFT ratio", "efficient trade count", "gain-from-trade ratio", _series_points(selected_raw, "trading", "efficient_trade_count", "gain_from_trade_ratio"))],
        ),
        encoding="utf-8",
    )
    (output / FIGURES[3]).write_text(_svg_forest(contrast_rows), encoding="utf-8")
    (output / FIGURES[4]).write_text(
        _svg_direct_market_transfer(direct_transfer_rows), encoding="utf-8"
    )
    (output / FIGURES[5]).write_text(
        _svg_benchmark_contract(scope_rows, headline, selected_raw), encoding="utf-8"
    )

    input_manifest = {}
    for key, path in sorted(paths.items()):
        input_manifest[key] = {
            "path": Path(os.path.relpath(path.resolve(), output.resolve())).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    output_manifest = {}
    for name in (*TABLES, *FIGURES):
        path = output / name
        output_manifest[name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    scientific_digest = hashlib.sha256(
        "".join(input_manifest[key]["sha256"] for key in sorted(input_manifest)).encode("ascii")
    ).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "generation_command": "PYTHONPATH=benchmark/src python benchmark/scripts/build_kdd_paper_artifacts.py",
        "scientific_digest": scientific_digest,
        "inputs": input_manifest,
        "outputs": output_manifest,
        "row_counts": {
            TABLES[0]: len(scope_rows),
            TABLES[1]: len(contrast_rows),
            TABLES[2]: len(profile_rows),
            TABLES[3]: len(incentive_rows),
            TABLES[4]: len(replication_rows),
            TABLES[5]: len(economic_scope_rows),
            TABLES[6]: len(qualification_rows),
        },
        "schemas": {
            "svg": {"width": 960, "height": 560, "requires": ["title", "desc"]},
            "tables": list(TABLES),
            "figures": list(FIGURES),
        },
    }
    (output / "paper_artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_paper_artifact_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key, item in manifest.get("inputs", {}).items():
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute():
            errors.append(f"absolute input path: {key}")
            continue
        input_path = (manifest_path.parent / relative).resolve()
        if not input_path.is_file():
            errors.append(f"missing input: {key}")
        elif _sha256(input_path) != item.get("sha256"):
            errors.append(f"input sha256 mismatch: {key}")
    for name, item in manifest.get("outputs", {}).items():
        output_path = manifest_path.parent / name
        if not output_path.is_file():
            errors.append(f"missing output: {name}")
        elif _sha256(output_path) != item.get("sha256"):
            errors.append(f"output sha256 mismatch: {name}")
    return {
        "valid": not errors,
        "errors": errors,
        "input_count": len(manifest.get("inputs", {})),
        "output_count": len(manifest.get("outputs", {})),
    }


__all__ = [
    "DEFAULT_INPUTS",
    "DEFAULT_OUTPUT_DIR",
    "FIGURES",
    "TABLES",
    "build_kdd_paper_artifacts",
    "verify_paper_artifact_manifest",
]
