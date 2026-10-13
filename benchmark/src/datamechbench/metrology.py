"""Measurement validation for outcome audits and source-block rankings."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from scipy.stats import kendalltau

from .metrics import MetricValue
from .models import BenchmarkResult
from .reference_evaluation import audit_reference_results
from .report import load_jsonl_results
from .runner import BenchmarkConfig, build_cases, run_benchmark

PRIMARY_METRIC_RULES: Mapping[str, Mapping[str, str]] = {
    "valuation": {
        "metric_id": "replication_owner_rank_change",
        "direction": "lower",
    },
    "procurement": {"metric_id": "oracle_ratio", "direction": "higher"},
    "trading": {"metric_id": "gain_from_trade_ratio", "direction": "higher"},
}
OUTPUT_NAMES = (
    "mutation_panel.csv",
    "block_reliability.csv",
    "reliability_curve.csv",
    "summary.json",
)
HEADLINE_METHODS: Mapping[str, tuple[str, ...]] = {
    "valuation": (
        "shapley_exact",
        "tmc_shapley",
        "banzhaf_exact",
        "knn_shapley",
        "volume_shapley",
        "robust_volume_shapley",
    ),
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
SCIENTIFIC_OPERATORS: Mapping[str, tuple[str, ...]] = {
    "valuation": ("score_perturbation", "stored_metric_tampering"),
    "procurement": (
        "allocation_deletion",
        "payment_perturbation",
        "unknown_actor",
        "stored_metric_tampering",
    ),
    "trading": (
        "allocation_deletion",
        "payment_perturbation",
        "unknown_actor",
        "stored_metric_tampering",
    ),
}
BENIGN_OPERATORS = ("runtime_only", "canonical_reordering")


@dataclass(frozen=True)
class MutationRecord:
    mutation_id: str
    operator_id: str
    mutation_kind: str
    track: str
    method_id: str
    case_id: str
    run_id: str
    expected_detected: bool
    detected: bool
    audit_passed: bool
    mismatch_count: int
    error_count: int


@dataclass(frozen=True)
class MutationPanel:
    records: tuple[MutationRecord, ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class TrackReliability:
    track: str
    metric_id: str
    direction: str
    block_count: int
    method_count: int
    full_winner_ids: tuple[str, ...]
    leave_one_out_exact_winner_rate: float
    leave_one_out_mean_jaccard: float
    leave_one_out_mean_rank_tau: float
    minimum_blocks_with_full_recovery: int | None


@dataclass(frozen=True)
class ReliabilityCurvePoint:
    track: str
    metric_id: str
    direction: str
    block_subset_size: int
    subset_count: int
    exact_winner_set_rate: float
    mean_winner_jaccard: float
    mean_rank_tau: float


@dataclass(frozen=True)
class ReliabilityReport:
    tracks: Mapping[str, TrackReliability]
    curve: tuple[ReliabilityCurvePoint, ...]


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


def _metric_number(row: BenchmarkResult, metric_id: str) -> float | None:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        if not raw.applicable or raw.value is None:
            return None
        raw = raw.value
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _reverse_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _reverse_mapping(item)
            for key, item in reversed(tuple(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_mapping(item) for item in value]
    return value


def _has_numeric_metric(row: BenchmarkResult) -> bool:
    return any(
        isinstance(raw, MetricValue)
        and raw.applicable
        and isinstance(raw.value, (int, float))
        and not isinstance(raw.value, bool)
        for raw in row.metrics.values()
    )


def _operator_applicable(row: BenchmarkResult, operator_id: str) -> bool:
    outcome = row.outcome or {}
    if row.status != "completed":
        return False
    if operator_id == "score_perturbation":
        return isinstance(outcome.get("scores"), Mapping) and bool(outcome["scores"])
    if operator_id == "allocation_deletion":
        return isinstance(outcome.get("allocations"), list) and bool(
            outcome["allocations"]
        )
    if operator_id == "payment_perturbation":
        return isinstance(outcome.get("payments"), list) and bool(outcome["payments"])
    if operator_id == "unknown_actor":
        allocations = outcome.get("allocations")
        return (
            isinstance(allocations, list)
            and bool(allocations)
            and isinstance(allocations[0], Mapping)
            and bool(str(allocations[0].get("actor_id", "")))
        )
    if operator_id == "stored_metric_tampering":
        return _has_numeric_metric(row)
    if operator_id in BENIGN_OPERATORS:
        return isinstance(outcome, Mapping)
    raise ValueError(f"unknown metrology operator: {operator_id}")


def _mutate_outcome(
    rows: tuple[BenchmarkResult, ...], index: int, operator_id: str
) -> tuple[BenchmarkResult, ...]:
    mutated = list(rows)
    if operator_id == "score_perturbation":
        outcome = dict(mutated[index].outcome or {})
        scores = dict(outcome["scores"])
        owner = sorted(scores)[0]
        scores[owner] = float(scores[owner]) + 0.5
        outcome["scores"] = scores
        mutated[index] = replace(mutated[index], outcome=outcome)
    elif operator_id == "allocation_deletion":
        outcome = dict(mutated[index].outcome or {})
        outcome["selected_ids"] = []
        outcome["allocations"] = []
        mutated[index] = replace(mutated[index], outcome=outcome)
    elif operator_id == "payment_perturbation":
        outcome = dict(mutated[index].outcome or {})
        payments = [dict(item) for item in outcome["payments"]]
        payments[0]["amount"] = str(Decimal(payments[0]["amount"]) + Decimal("1"))
        outcome["payments"] = payments
        mutated[index] = replace(mutated[index], outcome=outcome)
    elif operator_id == "unknown_actor":
        outcome = dict(mutated[index].outcome or {})
        allocations = [dict(item) for item in outcome["allocations"]]
        allocations[0]["actor_id"] = "unknown-actor"
        outcome["allocations"] = allocations
        mutated[index] = replace(mutated[index], outcome=outcome)
    elif operator_id == "stored_metric_tampering":
        metrics = dict(mutated[index].metrics)
        for metric_id, raw in metrics.items():
            if isinstance(raw, MetricValue) and raw.applicable and isinstance(
                raw.value, (int, float)
            ) and not isinstance(raw.value, bool):
                metrics[metric_id] = replace(raw, value=float(raw.value) + 0.25)
                break
        else:
            raise ValueError("probe has no mutable numeric metric")
        mutated[index] = replace(mutated[index], metrics=metrics)
    elif operator_id == "runtime_only":
        mutated[index] = replace(
            mutated[index], runtime_seconds=mutated[index].runtime_seconds + 10.0
        )
    elif operator_id == "canonical_reordering":
        mutated[index] = replace(
            mutated[index], outcome=_reverse_mapping(mutated[index].outcome)
        )
    else:
        raise ValueError(f"unknown metrology operator: {operator_id}")
    return tuple(mutated)


def audit_mutation_panel(
    results: Iterable[BenchmarkResult],
    *,
    cases: Mapping[str, Iterable[Any]],
    headline_methods: Mapping[str, Iterable[str]],
) -> MutationPanel:
    """Measure evaluator sensitivity and specificity for every headline method."""

    rows = tuple(results)
    records: list[MutationRecord] = []
    expected_methods = {
        track: tuple(str(method_id) for method_id in method_ids)
        for track, method_ids in headline_methods.items()
    }
    for track in sorted(expected_methods):
        if track not in SCIENTIFIC_OPERATORS:
            raise ValueError(f"unsupported headline track: {track}")
        for method_id in expected_methods[track]:
            method_rows = [
                (index, row)
                for index, row in enumerate(rows)
                if row.track == track
                and row.method_id == method_id
                and row.status == "completed"
            ]
            if not method_rows:
                raise ValueError(
                    f"missing headline probe method for {track}: {method_id}"
                )
            for operator_id in (*SCIENTIFIC_OPERATORS[track], *BENIGN_OPERATORS):
                applicable = next(
                    (
                        (index, row)
                        for index, row in method_rows
                        if _operator_applicable(row, operator_id)
                    ),
                    None,
                )
                if applicable is None:
                    raise ValueError(
                        f"{track} method {method_id} has no applicable outcome "
                        f"for {operator_id}"
                    )
                index, row = applicable
                expected = operator_id in SCIENTIFIC_OPERATORS[track]
                audit = audit_reference_results(
                    _mutate_outcome(rows, index, operator_id), cases=cases
                )
                detected = not audit.passed
                records.append(
                    MutationRecord(
                        mutation_id=(
                            f"{track}:{method_id}:{operator_id}:"
                            f"{row.case_id}:{row.run_id}"
                        ),
                        operator_id=operator_id,
                        mutation_kind=(
                            "scientific_corruption" if expected else "benign_control"
                        ),
                        track=track,
                        method_id=method_id,
                        case_id=row.case_id,
                        run_id=row.run_id,
                        expected_detected=expected,
                        detected=detected,
                        audit_passed=audit.passed,
                        mismatch_count=len(audit.metric_mismatches),
                        error_count=len(audit.errors),
                    )
                )
    scientific = tuple(row for row in records if row.expected_detected)
    benign = tuple(row for row in records if not row.expected_detected)
    scientific_detected = sum(row.detected for row in scientific)
    benign_accepted = sum(not row.detected for row in benign)
    covered_methods = {
        (row.track, row.method_id)
        for row in records
    }
    covered_method_ids = {
        track: sorted(
            method_id
            for observed_track, method_id in covered_methods
            if observed_track == track
        )
        for track in sorted(expected_methods)
    }
    operator_cell_counts = {
        track: {
            operator_id: sum(
                row.track == track and row.operator_id == operator_id
                for row in records
            )
            for operator_id in sorted(
                (*SCIENTIFIC_OPERATORS[track], *BENIGN_OPERATORS)
            )
        }
        for track in sorted(expected_methods)
    }
    expected_method_count = sum(len(methods) for methods in expected_methods.values())
    summary = {
        "headline_method_count": expected_method_count,
        "covered_method_count": len(covered_methods),
        "scientific_mutation_count": len(scientific),
        "scientific_mutations_detected": scientific_detected,
        "benign_control_count": len(benign),
        "benign_controls_accepted": benign_accepted,
        "sensitivity": scientific_detected / len(scientific),
        "specificity": benign_accepted / len(benign),
        "track_method_counts": {
            track: len(methods)
            for track, methods in sorted(expected_methods.items())
        },
        "covered_method_ids": covered_method_ids,
        "operator_cell_counts": operator_cell_counts,
    }
    return MutationPanel(tuple(records), summary)


def _winner_ids(scores: Mapping[str, float], direction: str) -> tuple[str, ...]:
    optimum = min(scores.values()) if direction == "lower" else max(scores.values())
    return tuple(
        sorted(
            method_id
            for method_id, value in scores.items()
            if math.isclose(value, optimum, rel_tol=1e-12, abs_tol=1e-12)
        )
    )


def _rank_vector(scores: Mapping[str, float], methods: tuple[str, ...], direction: str) -> list[float]:
    orientation = 1.0 if direction == "lower" else -1.0
    return [orientation * scores[method] for method in methods]


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 1.0


def analyze_block_reliability(
    results: Iterable[BenchmarkResult],
) -> ReliabilityReport:
    """Enumerate source-block subsets without treating seeds as markets."""

    rows = tuple(results)
    tracks: dict[str, TrackReliability] = {}
    curve: list[ReliabilityCurvePoint] = []
    for track, rule in PRIMARY_METRIC_RULES.items():
        metric_id = rule["metric_id"]
        direction = rule["direction"]
        values: dict[tuple[str, str], list[float]] = {}
        observed_blocks: set[str] = set()
        for row in rows:
            if row.track != track or row.status != "completed":
                continue
            value = _metric_number(row, metric_id)
            if value is None:
                continue
            if row.metadata.get("primary_metric_eligible") is False:
                continue
            block = str(row.metadata.get("independent_block", "")).strip()
            if not block:
                raise ValueError(f"{track} primary rows require independent_block")
            observed_blocks.add(block)
            values.setdefault((block, row.method_id), []).append(value)
        if not observed_blocks:
            continue
        blocks = tuple(sorted(observed_blocks))
        method_sets = [
            {method for block, method in values if block == block_id}
            for block_id in blocks
        ]
        methods = tuple(sorted(set.intersection(*method_sets)))
        if not methods:
            raise ValueError(f"{track} has no method with complete block coverage")
        block_scores = {
            (block, method): fmean(values[(block, method)])
            for block in blocks
            for method in methods
        }

        def subset_scores(subset: tuple[str, ...]) -> dict[str, float]:
            return {
                method: fmean(block_scores[(block, method)] for block in subset)
                for method in methods
            }

        full_scores = subset_scores(blocks)
        full_winners = _winner_ids(full_scores, direction)
        full_vector = _rank_vector(full_scores, methods, direction)
        curve_by_size: dict[int, ReliabilityCurvePoint] = {}
        for size in range(1, len(blocks) + 1):
            subsets = tuple(combinations(blocks, size))
            winner_sets: list[tuple[str, ...]] = []
            taus: list[float] = []
            for subset in subsets:
                scores = subset_scores(subset)
                winner_sets.append(_winner_ids(scores, direction))
                subset_vector = _rank_vector(scores, methods, direction)
                tau = float(kendalltau(full_vector, subset_vector).statistic)
                if math.isfinite(tau):
                    taus.append(tau)
                else:
                    both_constant = (
                        len(set(full_vector)) == 1
                        and len(set(subset_vector)) == 1
                    )
                    taus.append(1.0 if both_constant else 0.0)
            point = ReliabilityCurvePoint(
                track=track,
                metric_id=metric_id,
                direction=direction,
                block_subset_size=size,
                subset_count=len(subsets),
                exact_winner_set_rate=fmean(
                    winners == full_winners for winners in winner_sets
                ),
                mean_winner_jaccard=fmean(
                    _jaccard(winners, full_winners) for winners in winner_sets
                ),
                mean_rank_tau=fmean(taus),
            )
            curve.append(point)
            curve_by_size[size] = point
        leave_one = curve_by_size[max(1, len(blocks) - 1)]
        minimum = next(
            (
                size
                for size in range(1, len(blocks) + 1)
                if math.isclose(
                    curve_by_size[size].exact_winner_set_rate,
                    1.0,
                    abs_tol=1e-12,
                )
            ),
            None,
        )
        tracks[track] = TrackReliability(
            track=track,
            metric_id=metric_id,
            direction=direction,
            block_count=len(blocks),
            method_count=len(methods),
            full_winner_ids=full_winners,
            leave_one_out_exact_winner_rate=leave_one.exact_winner_set_rate,
            leave_one_out_mean_jaccard=leave_one.mean_winner_jaccard,
            leave_one_out_mean_rank_tau=leave_one.mean_rank_tau,
            minimum_blocks_with_full_recovery=minimum,
        )
    return ReliabilityReport(tracks, tuple(curve))


def build_metrology_probe() -> tuple[
    tuple[BenchmarkResult, ...],
    Mapping[str, tuple[Any, ...]],
    Mapping[str, tuple[str, ...]],
]:
    """Run the fixed compact probe used by the method-complete mutation matrix."""

    case_ids = {
        "valuation": "C-real-clean",
        "procurement": "P-C-add-b70",
        "trading": "S6-double-auction",
    }
    catalog = build_cases()
    cases = {
        track: tuple(case for case in catalog[track] if case.case_id == case_id)
        for track, case_id in case_ids.items()
    }
    if any(len(track_cases) != 1 for track_cases in cases.values()):
        raise RuntimeError("metrology probe requires exactly one case per track")
    methods = {
        track: {method_id: {} for method_id in method_ids}
        for track, method_ids in HEADLINE_METHODS.items()
    }
    methods["procurement"]["budget_optimum"] = {}
    methods["trading"]["efficient_clearing"] = {}
    config = BenchmarkConfig(
        name="kdd-metrology-probe-v2",
        output_dir="unused",
        seeds=(1701,),
        methods=methods,
        case_ids={
            track: tuple(case.case_id for case in track_cases)
            for track, track_cases in cases.items()
        },
        strategic_audit=False,
    )
    results = run_benchmark(config, cases=cases)
    expected_rows = sum(len(method_ids) for method_ids in methods.values())
    if len(results) != expected_rows or any(row.status != "completed" for row in results):
        raise RuntimeError(
            f"metrology probe must produce {expected_rows} completed rows"
        )
    return results, cases, HEADLINE_METHODS


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_benchmark_metrology(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    v1_results: str | Path,
    v2_results: str | Path,
) -> dict[str, Any]:
    """Build mutation and source-block reliability evidence."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)
    probe, probe_cases, headline_methods = build_metrology_probe()
    panel = audit_mutation_panel(
        probe,
        cases=probe_cases,
        headline_methods=headline_methods,
    )
    _write_csv(
        output / "mutation_panel.csv",
        (
            {
                "mutation_id": row.mutation_id,
                "operator_id": row.operator_id,
                "mutation_kind": row.mutation_kind,
                "track": row.track,
                "method_id": row.method_id,
                "case_id": row.case_id,
                "run_id": row.run_id,
                "expected_detected": row.expected_detected,
                "detected": row.detected,
                "audit_passed": row.audit_passed,
                "mismatch_count": row.mismatch_count,
                "error_count": row.error_count,
            }
            for row in panel.records
        ),
        (
            "mutation_id",
            "operator_id",
            "mutation_kind",
            "track",
            "method_id",
            "case_id",
            "run_id",
            "expected_detected",
            "detected",
            "audit_passed",
            "mismatch_count",
            "error_count",
        ),
    )
    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    combined = (
        *load_jsonl_results(resolve(v1_results)),
        *load_jsonl_results(resolve(v2_results)),
    )
    reliability = analyze_block_reliability(combined)
    _write_csv(
        output / "block_reliability.csv",
        (
            {
                **vars(row),
                "full_winner_ids": ";".join(row.full_winner_ids),
            }
            for row in reliability.tracks.values()
        ),
        (
            "track",
            "metric_id",
            "direction",
            "block_count",
            "method_count",
            "full_winner_ids",
            "leave_one_out_exact_winner_rate",
            "leave_one_out_mean_jaccard",
            "leave_one_out_mean_rank_tau",
            "minimum_blocks_with_full_recovery",
        ),
    )
    _write_csv(
        output / "reliability_curve.csv",
        (vars(row) for row in reliability.curve),
        (
            "track",
            "metric_id",
            "direction",
            "block_subset_size",
            "subset_count",
            "exact_winner_set_rate",
            "mean_winner_jaccard",
            "mean_rank_tau",
        ),
    )
    mutation_valid = all(
        row.detected == row.expected_detected for row in panel.records
    )
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-benchmark-metrology-v1",
        "valid": mutation_valid and set(reliability.tracks) == set(PRIMARY_METRIC_RULES),
        "mutation_panel": dict(panel.summary),
        "reliability": {
            "track_count": len(reliability.tracks),
            "block_counts": {
                track: row.block_count
                for track, row in sorted(reliability.tracks.items())
            },
            "full_winner_ids": {
                track: list(row.full_winner_ids)
                for track, row in sorted(reliability.tracks.items())
            },
            "leave_one_out_exact_winner_rate": {
                track: row.leave_one_out_exact_winner_rate
                for track, row in sorted(reliability.tracks.items())
            },
        },
        "claim_boundary": (
            "Mutation sensitivity validates the declared finite method/operator "
            "matrix on one controlled probe case per track; it is not a general "
            "correctness or security guarantee. Block stability is descriptive "
            "over five registered sources per track "
            "and is not population inference."
        ),
    }
    _write_json(output / "summary.json", summary)
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "benchmark_metrology",
        "inputs": [
            {"path": str(v1_results), "sha256": _sha256(resolve(v1_results))},
            {"path": str(v2_results), "sha256": _sha256(resolve(v2_results))},
        ],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)}
            for name in OUTPUT_NAMES
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return summary


def _verify_mutation_matrix(directory: Path) -> bool:
    """Check that the CSV realizes the declared method/operator contract."""

    try:
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        with (directory / "mutation_panel.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            rows = tuple(csv.DictReader(stream))
    except (OSError, csv.Error, json.JSONDecodeError):
        return False

    expected_cells = {
        (track, method_id, operator_id)
        for track, method_ids in HEADLINE_METHODS.items()
        for method_id in method_ids
        for operator_id in (*SCIENTIFIC_OPERATORS[track], *BENIGN_OPERATORS)
    }
    observed_cells: set[tuple[str, str, str]] = set()
    mutation_ids: set[str] = set()
    scientific_count = 0
    scientific_detected = 0
    benign_count = 0
    benign_accepted = 0
    for row in rows:
        track = row.get("track", "")
        method_id = row.get("method_id", "")
        operator_id = row.get("operator_id", "")
        cell = (track, method_id, operator_id)
        mutation_id = row.get("mutation_id", "")
        if (
            cell not in expected_cells
            or cell in observed_cells
            or not mutation_id
            or mutation_id in mutation_ids
        ):
            return False
        observed_cells.add(cell)
        mutation_ids.add(mutation_id)

        scientific = operator_id in SCIENTIFIC_OPERATORS[track]
        expected_detected = row.get("expected_detected") == "True"
        detected = row.get("detected") == "True"
        audit_passed = row.get("audit_passed") == "True"
        if (
            row.get("expected_detected") not in {"True", "False"}
            or row.get("detected") not in {"True", "False"}
            or row.get("audit_passed") not in {"True", "False"}
            or expected_detected != scientific
            or detected != expected_detected
            or audit_passed == detected
            or row.get("mutation_kind")
            != ("scientific_corruption" if scientific else "benign_control")
        ):
            return False
        if scientific:
            scientific_count += 1
            scientific_detected += int(detected)
        else:
            benign_count += 1
            benign_accepted += int(not detected)

    if observed_cells != expected_cells:
        return False

    covered_method_ids = {
        track: sorted(method_ids)
        for track, method_ids in sorted(HEADLINE_METHODS.items())
    }
    operator_cell_counts = {
        track: {
            operator_id: len(method_ids)
            for operator_id in sorted(
                (*SCIENTIFIC_OPERATORS[track], *BENIGN_OPERATORS)
            )
        }
        for track, method_ids in sorted(HEADLINE_METHODS.items())
    }
    expected_summary = {
        "headline_method_count": sum(len(ids) for ids in HEADLINE_METHODS.values()),
        "covered_method_count": sum(len(ids) for ids in HEADLINE_METHODS.values()),
        "scientific_mutation_count": scientific_count,
        "scientific_mutations_detected": scientific_detected,
        "benign_control_count": benign_count,
        "benign_controls_accepted": benign_accepted,
        "sensitivity": scientific_detected / scientific_count,
        "specificity": benign_accepted / benign_count,
        "track_method_counts": {
            track: len(method_ids)
            for track, method_ids in sorted(HEADLINE_METHODS.items())
        },
        "covered_method_ids": covered_method_ids,
        "operator_cell_counts": operator_cell_counts,
    }
    return summary.get("mutation_panel") == expected_summary


def verify_benchmark_metrology(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"], "output_count": 0}
    records = payload.get("outputs")
    if payload.get("schema_version") != "1.0" or not isinstance(records, list):
        return {"valid": False, "errors": ["invalid_manifest_schema"], "output_count": 0}
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        name = str(record.get("path", "")) if isinstance(record, Mapping) else ""
        expected = str(record.get("sha256", "")) if isinstance(record, Mapping) else ""
        if name in seen or name not in OUTPUT_NAMES:
            errors.append(f"invalid_output:{name or 'missing'}")
            continue
        seen.add(name)
        target = path.parent / name
        if not target.is_file():
            errors.append(f"missing:{name}")
        elif _sha256(target) != expected:
            errors.append(f"hash_mismatch:{name}")
    for name in sorted(set(OUTPUT_NAMES) - seen):
        errors.append(f"missing_binding:{name}")
    if not errors and not _verify_mutation_matrix(path.parent):
        errors.append("mutation_matrix_summary_mismatch")
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "PRIMARY_METRIC_RULES",
    "ReliabilityReport",
    "audit_mutation_panel",
    "analyze_block_reliability",
    "build_benchmark_metrology",
    "build_metrology_probe",
    "verify_benchmark_metrology",
]
