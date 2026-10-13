"""Evaluator-side recomputation of reference metrics from persisted outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .metrics import (
    MetricValue,
    evaluate_procurement_metrics,
    evaluate_trading_metrics,
    evaluate_valuation_metrics,
)
from .models import BenchmarkResult
from .outcomes import parse_outcome
from .registry import MethodRegistry, validate_output
from .report import load_jsonl_results
from .runner import build_registry

EXECUTION_DEPENDENT_METRIC_IDS = frozenset(
    {
        "allocation_monotonicity_violation",
        "critical_payment_gap",
        "max_deviation_gain",
        "profitable_deviation_count",
        "runtime_seconds",
        "trading_max_deviation_gain",
    }
)


@dataclass(frozen=True)
class ReferenceOutcomeAudit:
    passed: bool
    result_rows: int
    completed_rows: int
    outcome_rows: int
    auditable_rows: int
    recomputed_metric_count: int
    execution_dependent_metric_count: int
    execution_dependent_metric_ids: tuple[str, ...]
    track_rows: Mapping[str, int]
    metric_mismatches: tuple[Mapping[str, Any], ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric_payload(value: Any) -> Any:
    if isinstance(value, MetricValue):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {
            str(key): _metric_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple):
        return [_metric_payload(item) for item in value]
    return value


def _case_index(cases: Mapping[str, Iterable[Any]]) -> dict[tuple[str, str], Any]:
    index: dict[tuple[str, str], Any] = {}
    for track, track_cases in cases.items():
        for case in track_cases:
            key = (str(track), str(case.case_id))
            if key in index:
                raise ValueError(f"duplicate reference case: {track}/{case.case_id}")
            index[key] = case
    return index


def audit_reference_results(
    results: Iterable[BenchmarkResult],
    *,
    cases: Mapping[str, Iterable[Any]],
    registry: MethodRegistry | None = None,
) -> ReferenceOutcomeAudit:
    """Recompute every outcome-derived stored metric without rerunning methods."""

    rows = tuple(results)
    registry = registry or build_registry()
    specs = {spec.method_id: spec for spec in registry.specs()}
    case_by_key = _case_index(cases)
    errors: list[str] = []
    outcomes: dict[str, Any] = {}
    row_cases: dict[str, Any] = {}

    completed = tuple(row for row in rows if row.status == "completed")
    for row in completed:
        if row.outcome is None:
            errors.append(f"missing_outcome:{row.run_id}")
            continue
        case = case_by_key.get((row.track, row.case_id))
        if case is None:
            errors.append(f"unknown_case:{row.run_id}:{row.track}/{row.case_id}")
            continue
        spec = specs.get(row.method_id)
        if spec is None:
            errors.append(f"unknown_method:{row.run_id}:{row.method_id}")
            continue
        try:
            output = parse_outcome(row.track, row.outcome)
            public_case = case if row.track == "valuation" else case.public
            validate_output(spec, public_case, output)
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid_outcome:{row.run_id}:{exc}")
            continue
        outcomes[row.run_id] = output
        row_cases[row.run_id] = case

    def oracle_for(row: BenchmarkResult):
        exact = [
            candidate
            for candidate in completed
            if candidate.run_id in outcomes
            and candidate.track == row.track
            and candidate.case_id == row.case_id
            and specs[candidate.method_id].role == "oracle"
            and candidate.seed == row.seed
        ]
        if exact:
            return outcomes[exact[0].run_id]
        fallback = [
            candidate
            for candidate in completed
            if candidate.run_id in outcomes
            and candidate.track == row.track
            and candidate.case_id == row.case_id
            and specs[candidate.method_id].role == "oracle"
        ]
        return outcomes[fallback[0].run_id] if fallback else None

    mismatches: list[dict[str, Any]] = []
    recomputed_count = 0
    execution_dependent_count = 0
    for row in completed:
        if row.run_id not in outcomes:
            continue
        case = row_cases[row.run_id]
        output = outcomes[row.run_id]
        spec = specs[row.method_id]
        if row.track == "valuation":
            peers: list[Any] = [
                outcomes[candidate.run_id]
                for candidate in completed
                if candidate.run_id in outcomes
                and candidate.run_id != row.run_id
                and candidate.track == "valuation"
                and candidate.method_id == row.method_id
                and candidate.case_id == row.case_id
            ]
            if case.metadata.get("duplicate_pair"):
                peers.extend(
                    (row_cases[candidate.run_id], outcomes[candidate.run_id])
                    for candidate in completed
                    if candidate.run_id in outcomes
                    and candidate.track == "valuation"
                    and candidate.method_id == row.method_id
                    and candidate.case_id == "C-real-clean"
                    and candidate.seed == row.seed
                )
            baseline = case.metadata.get("replication_baseline_case_id")
            if baseline and case.case_id != baseline:
                peers.extend(
                    (row_cases[candidate.run_id], outcomes[candidate.run_id])
                    for candidate in completed
                    if candidate.run_id in outcomes
                    and candidate.track == "valuation"
                    and candidate.method_id == row.method_id
                    and candidate.case_id == baseline
                    and candidate.seed == row.seed
                )
            recomputed = evaluate_valuation_metrics(
                case,
                output,
                oracle_output=oracle_for(row),
                peer_outputs=peers,
            )
        elif row.track == "procurement":
            recomputed = evaluate_procurement_metrics(
                case,
                output,
                spec,
                oracle_for(row),
                method=None,
                seed=row.seed,
            )
        else:
            recomputed = evaluate_trading_metrics(
                case,
                output,
                spec,
                oracle_for(row),
                method=None,
                seed=row.seed,
            )
        for metric_id, observed in row.metrics.items():
            if metric_id in EXECUTION_DEPENDENT_METRIC_IDS:
                execution_dependent_count += 1
                continue
            recomputed_count += 1
            expected = recomputed.get(metric_id)
            if expected is None or _metric_payload(observed) != _metric_payload(expected):
                mismatches.append(
                    {
                        "run_id": row.run_id,
                        "track": row.track,
                        "method_id": row.method_id,
                        "case_id": row.case_id,
                        "metric_id": metric_id,
                        "stored": _metric_payload(observed),
                        "recomputed": _metric_payload(expected),
                    }
                )

    track_rows = {
        track: sum(row.track == track and row.status == "completed" for row in rows)
        for track in ("valuation", "procurement", "trading")
    }
    return ReferenceOutcomeAudit(
        passed=(
            not errors
            and not mismatches
            and len(outcomes) == len(completed)
        ),
        result_rows=len(rows),
        completed_rows=len(completed),
        outcome_rows=sum(row.outcome is not None for row in completed),
        auditable_rows=len(outcomes),
        recomputed_metric_count=recomputed_count,
        execution_dependent_metric_count=execution_dependent_count,
        execution_dependent_metric_ids=tuple(sorted(EXECUTION_DEPENDENT_METRIC_IDS)),
        track_rows=track_rows,
        metric_mismatches=tuple(mismatches),
        errors=tuple(errors),
    )


def write_reference_outcome_audit(
    results_path: str | Path,
    output_path: str | Path,
    *,
    cases: Mapping[str, Iterable[Any]],
    registry: MethodRegistry | None = None,
) -> Path:
    """Write a deterministic receipt binding outcome-derived metric agreement."""

    source = Path(results_path)
    audit = audit_reference_results(
        load_jsonl_results(source), cases=cases, registry=registry
    )
    payload = {
        "schema_version": "1.0",
        "report_kind": "reference_outcome_metric_recomputation",
        "metric_authority": "evaluator_recomputed_from_persisted_outcomes",
        "result_path": source.name,
        "result_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        **audit.to_dict(),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


__all__ = [
    "EXECUTION_DEPENDENT_METRIC_IDS",
    "ReferenceOutcomeAudit",
    "audit_reference_results",
    "write_reference_outcome_audit",
]
