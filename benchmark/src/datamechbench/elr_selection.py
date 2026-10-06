"""Leakage-safe development selection for budget-debited PG-ELR."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .methods.valuation_multifidelity import (
    BudgetDebitedConfig,
    complementary_probe_plan,
)


@dataclass(frozen=True)
class SelectionCell:
    dataset_id: str
    partition: str
    budget: int
    method_mae: float | None
    baseline_mae: float | None
    normalized_regret: float | None
    improved: bool | None
    status: str


@dataclass(frozen=True)
class CandidateEvaluation:
    config: BudgetDebitedConfig
    cells: tuple[SelectionCell, ...]
    status: str
    max_normalized_regret: float
    improved_cells: int
    unique_probe_high_calls: int
    failed_cells: int


@dataclass(frozen=True)
class SelectionFold:
    held_out_dataset: str
    training_datasets: tuple[str, ...]
    selected_config: BudgetDebitedConfig
    held_out_cells: tuple[SelectionCell, ...]


@dataclass(frozen=True)
class ProbeCandidateSummary:
    selected_config: BudgetDebitedConfig
    candidates: tuple[CandidateEvaluation, ...]
    folds: tuple[SelectionFold, ...]
    tie_tolerance: float


_FORBIDDEN_ROUTING_TOKENS = (
    "dataset",
    "model_family",
    "test_",
    "heldout",
    "confirmatory",
    "selected_after",
    "outcome",
)
_ALLOWED_ROUTING_KEYS = {
    "probe_median_mae",
    "probe_winners",
    "budget",
    "low_cost_ratio",
    "probe_players",
    "calibration_seed_count",
}
_FORBIDDEN_TOP_LEVEL = (
    "model_family",
    "test_metric",
    "test_utility",
    "heldout_metric",
    "confirmatory_result",
    "confirmatory_outcome",
    "selected_after_outcome",
)


def _validate_row(row: Mapping[str, Any]) -> None:
    for key in row:
        if any(token in str(key).lower() for token in _FORBIDDEN_TOP_LEVEL):
            raise ValueError(f"forbidden selection field: {key}")
    routing = row.get("routing_inputs", {})
    if not isinstance(routing, Mapping):
        raise ValueError("routing_inputs must be a mapping")
    for key in routing:
        lowered = str(key).lower()
        if key not in _ALLOWED_ROUTING_KEYS or any(
            token in lowered for token in _FORBIDDEN_ROUTING_TOKENS
        ):
            raise ValueError(f"forbidden routing input: {key}")


def _config_key(config: BudgetDebitedConfig) -> tuple[int, int]:
    return config.probe_players, len(config.calibration_seeds)


def _evaluate_candidate(
    rows: Sequence[Mapping[str, Any]],
    config: BudgetDebitedConfig,
    *,
    tie_tolerance: float,
) -> CandidateEvaluation:
    matching = [
        row
        for row in rows
        if (
            int(row["probe_players"]),
            int(row["calibration_seed_count"]),
        )
        == _config_key(config)
    ]
    grouped: dict[tuple[str, str, int], list[Mapping[str, Any]]] = {}
    for row in matching:
        key = (str(row["dataset_id"]), str(row["partition"]), int(row["budget"]))
        grouped.setdefault(key, []).append(row)
    cells: list[SelectionCell] = []
    for (dataset, partition, budget), cell_rows in sorted(grouped.items()):
        completed = [row for row in cell_rows if row.get("status") == "completed"]
        if len(completed) != len(cell_rows) or not completed:
            cells.append(
                SelectionCell(dataset, partition, budget, None, None, None, None, "failed")
            )
            continue
        method_mae = float(median(float(row["method_mae"]) for row in completed))
        baseline_mae = float(median(float(row["baseline_mae"]) for row in completed))
        if not math.isfinite(method_mae) or not math.isfinite(baseline_mae):
            cells.append(
                SelectionCell(dataset, partition, budget, None, None, None, None, "failed")
            )
            continue
        denominator = abs(baseline_mae)
        regret = (
            (method_mae - baseline_mae) / denominator
            if denominator > 0
            else method_mae - baseline_mae
        )
        improved = method_mae < baseline_mae * (1.0 - tie_tolerance)
        cells.append(
            SelectionCell(
                dataset,
                partition,
                budget,
                method_mae,
                baseline_mae,
                float(regret),
                improved,
                "completed",
            )
        )
    expected_cells = {
        (str(row["dataset_id"]), str(row["partition"]), int(row["budget"]))
        for row in rows
    }
    observed_cells = {(cell.dataset_id, cell.partition, cell.budget) for cell in cells}
    for dataset, partition, budget in sorted(expected_cells - observed_cells):
        cells.append(
            SelectionCell(dataset, partition, budget, None, None, None, None, "failed")
        )
    completed_regrets = [
        float(cell.normalized_regret)
        for cell in cells
        if cell.normalized_regret is not None
    ]
    failed_cells = sum(cell.status != "completed" for cell in cells)
    owner_count = max((int(row.get("owner_count", 8)) for row in matching), default=8)
    probe_calls = len(
        complementary_probe_plan(
            tuple(f"owner-{index}" for index in range(owner_count)),
            config.probe_players,
        ).unique_high_masks
    )
    return CandidateEvaluation(
        config=config,
        cells=tuple(sorted(cells, key=lambda cell: (cell.dataset_id, cell.partition, cell.budget))),
        status="failed" if failed_cells else "completed",
        max_normalized_regret=max(completed_regrets, default=float("inf")),
        improved_cells=sum(cell.improved is True for cell in cells),
        unique_probe_high_calls=probe_calls,
        failed_cells=failed_cells,
    )


def _rank(candidate: CandidateEvaluation) -> tuple[float, float, int, int, int]:
    return (
        float(candidate.status != "completed"),
        candidate.max_normalized_regret,
        -candidate.improved_cells,
        candidate.unique_probe_high_calls,
        len(candidate.config.calibration_seeds),
    )


def leave_one_dataset_out_select(
    rows: Iterable[Mapping[str, Any]],
    *,
    candidate_grid: Sequence[BudgetDebitedConfig],
    tie_tolerance: float = 0.01,
) -> ProbeCandidateSummary:
    """Select one fixed probe config and audit leave-one-dataset-out behavior."""

    materialized = tuple(dict(row) for row in rows)
    candidates = tuple(candidate_grid)
    if not materialized:
        raise ValueError("selection rows must not be empty")
    if not candidates or len({_config_key(item) for item in candidates}) != len(candidates):
        raise ValueError("candidate_grid must contain unique (k, m) configurations")
    if not math.isfinite(tie_tolerance) or not 0 <= tie_tolerance < 1:
        raise ValueError("tie_tolerance must be in [0, 1)")
    for row in materialized:
        _validate_row(row)
    evaluations = tuple(
        _evaluate_candidate(materialized, config, tie_tolerance=tie_tolerance)
        for config in candidates
    )
    selected = min(evaluations, key=_rank).config
    datasets = tuple(sorted({str(row["dataset_id"]) for row in materialized}))
    folds: list[SelectionFold] = []
    for held_out in datasets:
        training_rows = tuple(
            row for row in materialized if str(row["dataset_id"]) != held_out
        )
        training_evaluations = (
            tuple(
                _evaluate_candidate(training_rows, config, tie_tolerance=tie_tolerance)
                for config in candidates
            )
            if training_rows
            else evaluations
        )
        fold_selected = min(training_evaluations, key=_rank).config
        held_evaluation = _evaluate_candidate(
            tuple(row for row in materialized if str(row["dataset_id"]) == held_out),
            fold_selected,
            tie_tolerance=tie_tolerance,
        )
        folds.append(
            SelectionFold(
                held_out,
                tuple(dataset for dataset in datasets if dataset != held_out),
                fold_selected,
                held_evaluation.cells,
            )
        )
    return ProbeCandidateSummary(selected, evaluations, tuple(folds), tie_tolerance)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BudgetDebitedConfig):
        return {
            "probe_players": value.probe_players,
            "calibration_seeds": list(value.calibration_seeds),
            "calibration_budget": value.calibration_budget,
            "candidates": list(value.candidates),
            "fallback_method": value.fallback_method,
        }
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def write_selection_record(
    summary: ProbeCandidateSummary,
    path: Path,
    *,
    source_hashes: Mapping[str, str],
) -> str:
    """Atomically write a canonical, content-addressed selection record."""

    payload = {
        "schema_version": "1.0",
        "summary": _jsonable(summary),
        "source_hashes": dict(sorted(source_hashes.items())),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    selection_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    record = {**payload, "selection_hash": selection_hash}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target)
    return selection_hash


__all__ = [
    "CandidateEvaluation",
    "ProbeCandidateSummary",
    "SelectionCell",
    "SelectionFold",
    "leave_one_dataset_out_select",
    "write_selection_record",
]
