"""Frozen-wave mechanism selection followed by untouched-wave evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

import yaml

from .metrics import MetricValue
from .metrology import PRIMARY_METRIC_RULES
from .models import BenchmarkResult
from .report import load_jsonl_results

OUTPUT_NAMES = ("v1_selection.csv", "v2_evaluation.csv", "summary.json")


@dataclass(frozen=True)
class SelectionDecision:
    policy: str
    track: str
    metric_id: str
    direction: str
    objective: str
    source_wave: str
    source_block_count: int
    qualified_method_ids: tuple[str, ...]
    selected_method_ids: tuple[str, ...]
    selected_score: float


@dataclass(frozen=True)
class ProspectiveEvaluation:
    policy: str
    track: str
    method_id: str
    status: str
    qualification_preserved: bool
    v1_score: float
    v2_score: float | None
    v2_best_score: float | None
    v2_best_method_ids: tuple[str, ...]
    regret: float | None
    v2_block_count: int


@dataclass(frozen=True)
class ProspectiveSelectionReport:
    decisions: Mapping[str, SelectionDecision]
    evaluations: tuple[ProspectiveEvaluation, ...]
    policy_decisions: Mapping[str, Mapping[str, SelectionDecision]]
    policy_evaluations: tuple[ProspectiveEvaluation, ...]


def _metric_value(row: BenchmarkResult, metric_id: str) -> Any:
    raw = row.metrics.get(metric_id)
    if isinstance(raw, MetricValue):
        return raw.value if raw.applicable else None
    return raw


def _number(row: BenchmarkResult, metric_id: str) -> float | None:
    raw = _metric_value(row, metric_id)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _qualified(track: str, rows: tuple[BenchmarkResult, ...]) -> bool:
    if not rows:
        return False
    if track == "valuation":
        return True
    if track == "procurement":
        return all(
            _metric_value(row, "budget_violation") is False
            and _number(row, "seller_ir_violation_count") == 0.0
            for row in rows
        )
    if track == "trading":
        return all(
            _metric_value(row, "individual_rationality") is True
            and _metric_value(row, "weak_budget_balance") is True
            for row in rows
        )
    return False


def _wave_scores(
    results: tuple[BenchmarkResult, ...],
    track: str,
    methods: tuple[str, ...],
) -> tuple[dict[str, float], dict[str, float], dict[str, bool], dict[str, int]]:
    metric_id = PRIMARY_METRIC_RULES[track]["metric_id"]
    track_rows = tuple(
        row
        for row in results
        if row.track == track
        and row.status == "completed"
        and row.method_id in methods
        and row.metadata.get("primary_metric_eligible") is not False
    )
    global_blocks = {
        str(row.metadata.get("independent_block", "")).strip()
        for row in track_rows
        if _number(row, metric_id) is not None
    }
    global_blocks.discard("")
    scores: dict[str, float] = {}
    worst_scores: dict[str, float] = {}
    qualified: dict[str, bool] = {}
    block_counts: dict[str, int] = {}
    for method in methods:
        method_rows = tuple(row for row in track_rows if row.method_id == method)
        measurements: dict[str, list[float]] = {}
        for row in method_rows:
            value = _number(row, metric_id)
            block = str(row.metadata.get("independent_block", "")).strip()
            if value is not None and block:
                measurements.setdefault(block, []).append(value)
        if set(measurements) != global_blocks or not measurements:
            qualified[method] = False
            block_counts[method] = len(measurements)
            continue
        scores[method] = fmean(
            fmean(measurements[block]) for block in sorted(measurements)
        )
        block_scores = [fmean(measurements[block]) for block in sorted(measurements)]
        worst_scores[method] = (
            max(block_scores)
            if PRIMARY_METRIC_RULES[track]["direction"] == "lower"
            else min(block_scores)
        )
        qualified[method] = _qualified(track, method_rows)
        block_counts[method] = len(measurements)
    return scores, worst_scores, qualified, block_counts


def _winner_ids(scores: Mapping[str, float], direction: str) -> tuple[str, ...]:
    optimum = min(scores.values()) if direction == "lower" else max(scores.values())
    return tuple(
        sorted(
            method
            for method, value in scores.items()
            if math.isclose(value, optimum, rel_tol=1e-12, abs_tol=1e-12)
        )
    )


def run_prospective_selection(
    v1_results: Iterable[BenchmarkResult],
    v2_results: Iterable[BenchmarkResult],
    *,
    headline_methods: Mapping[str, tuple[str, ...]],
) -> ProspectiveSelectionReport:
    """Select only from v1, then evaluate the frozen selection on v2."""

    v1 = tuple(v1_results)
    v2 = tuple(v2_results)
    policies = ("raw", "constraint_aware", "robust")
    policy_decisions: dict[str, dict[str, SelectionDecision]] = {
        policy: {} for policy in policies
    }
    policy_evaluations: list[ProspectiveEvaluation] = []
    for track in ("valuation", "procurement", "trading"):
        if track not in headline_methods:
            continue
        methods = tuple(headline_methods[track])
        rule = PRIMARY_METRIC_RULES[track]
        v1_scores, v1_worst, v1_qualified, v1_blocks = _wave_scores(v1, track, methods)
        v2_scores, v2_worst, v2_qualified, v2_blocks = _wave_scores(v2, track, methods)
        for policy in policies:
            requires_qualification = policy != "raw"
            v1_objective = v1_worst if policy == "robust" else v1_scores
            candidates = {
                method: score
                for method, score in v1_objective.items()
                if not requires_qualification or v1_qualified.get(method, False)
            }
            if not candidates:
                raise ValueError(f"{track} has no v1 candidate for {policy}")
            selected = _winner_ids(candidates, rule["direction"])
            policy_decisions[policy][track] = SelectionDecision(
                policy=policy,
                track=track,
                metric_id=rule["metric_id"],
                direction=rule["direction"],
                objective="worst_block" if policy == "robust" else "mean_block",
                source_wave="v1",
                source_block_count=max(v1_blocks.values(), default=0),
                qualified_method_ids=tuple(
                    sorted(method for method in v1_scores if v1_qualified.get(method, False))
                ),
                selected_method_ids=selected,
                selected_score=candidates[selected[0]],
            )

            v2_objective = v2_worst if policy == "robust" else v2_scores
            v2_candidates = {
                method: score
                for method, score in v2_objective.items()
                if not requires_qualification or v2_qualified.get(method, False)
            }
            best_ids = _winner_ids(v2_candidates, rule["direction"]) if v2_candidates else ()
            best_score = v2_candidates[best_ids[0]] if best_ids else None
            for method in selected:
                objective_score = v2_objective.get(method)
                mean_score = v2_scores.get(method)
                preserved = bool(v2_qualified.get(method, False))
                if objective_score is None:
                    status, regret = "missing_v2_score", None
                elif requires_qualification and not preserved:
                    status, regret = "qualification_lost", None
                elif best_score is None:
                    status, regret = "no_qualified_v2_comparator", None
                else:
                    status = "evaluated" if preserved else "qualification_lost"
                    regret = (
                        objective_score - best_score
                        if rule["direction"] == "lower"
                        else best_score - objective_score
                    )
                    if math.isclose(regret, 0.0, abs_tol=1e-12):
                        regret = 0.0
                policy_evaluations.append(
                    ProspectiveEvaluation(
                        policy=policy,
                        track=track,
                        method_id=method,
                        status=status,
                        qualification_preserved=preserved,
                        v1_score=v1_scores[method],
                        v2_score=mean_score,
                        v2_best_score=best_score,
                        v2_best_method_ids=best_ids,
                        regret=regret,
                        v2_block_count=v2_blocks.get(method, 0),
                    )
                )
    legacy_decisions = policy_decisions["constraint_aware"]
    legacy_evaluations = tuple(
        row for row in policy_evaluations if row.policy == "constraint_aware"
    )
    return ProspectiveSelectionReport(
        legacy_decisions,
        legacy_evaluations,
        policy_decisions,
        tuple(policy_evaluations),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_prospective_selection(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    catalog_path: str | Path,
    v1_results: str | Path,
    v2_results: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)

    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    catalog = yaml.safe_load(resolve(catalog_path).read_text(encoding="utf-8")) or {}
    headline = {
        track: tuple(item["method_ids"])
        for track, item in catalog["flagships"].items()
    }
    report = run_prospective_selection(
        load_jsonl_results(resolve(v1_results)),
        load_jsonl_results(resolve(v2_results)),
        headline_methods=headline,
    )
    with (output / "v1_selection.csv").open("w", encoding="utf-8", newline="") as stream:
        columns = (
            "policy", "track", "metric_id", "direction", "objective", "source_wave", "source_block_count",
            "qualified_method_ids", "selected_method_ids", "selected_score",
        )
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for policy in ("raw", "constraint_aware", "robust"):
            for row in report.policy_decisions[policy].values():
                writer.writerow(
                    {
                        **vars(row),
                        "qualified_method_ids": ";".join(row.qualified_method_ids),
                        "selected_method_ids": ";".join(row.selected_method_ids),
                    }
                )
    with (output / "v2_evaluation.csv").open("w", encoding="utf-8", newline="") as stream:
        columns = (
            "policy", "track", "method_id", "status", "qualification_preserved", "v1_score",
            "v2_score", "v2_best_score", "v2_best_method_ids", "regret", "v2_block_count",
        )
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in report.policy_evaluations:
            writer.writerow({**vars(row), "v2_best_method_ids": ";".join(row.v2_best_method_ids)})
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-prospective-selection-v1",
        "valid": len(report.decisions) == 3,
        "selection_wave": "v1",
        "evaluation_wave": "v2",
        "selected_method_ids": {
            track: list(row.selected_method_ids) for track, row in report.decisions.items()
        },
        "evaluation_status": {
            f"{row.track}:{row.method_id}": row.status for row in report.evaluations
        },
        "regret": {
            f"{row.track}:{row.method_id}": row.regret for row in report.evaluations
        },
        "policy_selected_method_ids": {
            policy: {
                track: list(row.selected_method_ids)
                for track, row in decisions.items()
            }
            for policy, decisions in report.policy_decisions.items()
        },
        "policy_evaluation_status": {
            f"{row.policy}:{row.track}:{row.method_id}": row.status
            for row in report.policy_evaluations
        },
        "policy_regret": {
            f"{row.policy}:{row.track}:{row.method_id}": row.regret
            for row in report.policy_evaluations
        },
        "claim_boundary": (
            "Selections are frozen from v1 only and evaluated on v2 without reselection; "
            "the two waves are not pooled for confirmatory inference."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "prospective_selection",
        "inputs": [
            {"path": str(catalog_path), "sha256": _sha256(resolve(catalog_path))},
            {"path": str(v1_results), "sha256": _sha256(resolve(v1_results))},
            {"path": str(v2_results), "sha256": _sha256(resolve(v2_results))},
        ],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_prospective_selection(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    errors: list[str] = []
    seen: set[str] = set()
    for record in payload.get("outputs", []):
        name = str(record.get("path", ""))
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_or_invalid:{name}")
        elif _sha256(target) != str(record.get("sha256", "")):
            errors.append(f"hash_mismatch:{name}")
    errors.extend(f"missing_binding:{name}" for name in sorted(set(OUTPUT_NAMES) - seen))
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "ProspectiveEvaluation",
    "ProspectiveSelectionReport",
    "SelectionDecision",
    "build_prospective_selection",
    "run_prospective_selection",
    "verify_prospective_selection",
]
