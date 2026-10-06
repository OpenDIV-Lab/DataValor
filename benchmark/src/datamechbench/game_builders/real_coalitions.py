"""Atomic paired coalition games trained from real owner data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..coalition_games import CoalitionGameTable
from .real_data import RealDatasetManifest
from .real_features import FeatureArtifact
from .real_models import ModelTrajectoryConfig, build_trajectory

FIDELITIES = ("low", "medium", "high")
PROBABILITY_EPSILON = 1e-12


def classification_utility(
    probabilities: np.ndarray, targets: np.ndarray, *, n_classes: int
) -> float:
    probabilities = np.asarray(probabilities, dtype=np.float64)
    targets = np.asarray(targets, dtype=np.int64)
    selected = probabilities[np.arange(len(targets)), targets]
    return float(math.log(n_classes) + np.mean(np.log(np.clip(selected, PROBABILITY_EPSILON, 1.0))))


def regression_utility(predictions: np.ndarray, targets: np.ndarray) -> float:
    residual = np.asarray(predictions, dtype=np.float64) - np.asarray(
        targets, dtype=np.float64
    )
    return -float(np.mean(residual * residual))


@dataclass(frozen=True)
class RealCoalitionRecord:
    mask: int
    utilities: Mapping[str, float]
    fit_seconds: float
    checkpoint_hashes: Mapping[str, str]
    input_hash: str


@dataclass(frozen=True)
class RealCoalitionTables:
    tables: Mapping[str, CoalitionGameTable]
    records: Mapping[int, RealCoalitionRecord]
    input_hash: str
    content_hash: str
    trajectory_builds: int


@dataclass(frozen=True)
class BudgetApplicability:
    budget: float
    applicable: bool
    reason: str | None
    fixed_cost: float
    spent: float


@dataclass(frozen=True)
class CostCalibration:
    n_owners: int
    masks: tuple[int, ...]
    ratio_masks: tuple[int, ...]
    timings: Mapping[int, tuple[float, float]]
    ratio_median: float
    ratio_q1: float
    ratio_q3: float
    preprocessing_seconds: float
    fixed_high_equivalent: Mapping[str, float]

    def budget_status(self, budget: float, *, view: str = "median") -> BudgetApplicability:
        if view not in self.fixed_high_equivalent:
            raise ValueError(f"unknown accounting view: {view}")
        fixed = self.fixed_high_equivalent[view]
        if fixed > budget:
            return BudgetApplicability(
                budget, False, "fixed_low_table_cost_exceeds_budget", fixed, 0.0
            )
        return BudgetApplicability(budget, True, None, fixed, fixed)


def calibration_masks(n_owners: int) -> tuple[int, ...]:
    if n_owners < 2:
        raise ValueError("cost calibration requires at least two owners")
    return (0, 1, (1 << (n_owners // 2)) - 1, (1 << n_owners) - 1)


def calibrate_fidelity_cost(
    *,
    n_owners: int,
    observed_timings: Mapping[int, tuple[float, float]] | None = None,
    low_runner: Any | None = None,
    high_runner: Any | None = None,
    preprocessing_seconds: float = 0.0,
) -> CostCalibration:
    masks = calibration_masks(n_owners)
    if observed_timings is None:
        if low_runner is None or high_runner is None:
            raise ValueError("standalone low_runner and high_runner are required")
        measured: dict[int, tuple[float, float]] = {0: (0.0, 0.0)}
        for mask in masks[1:]:
            started = time.perf_counter()
            low_runner(mask)
            low_seconds = time.perf_counter() - started
            started = time.perf_counter()
            high_runner(mask)
            high_seconds = time.perf_counter() - started
            measured[mask] = (low_seconds, high_seconds)
    else:
        measured = {int(mask): tuple(values) for mask, values in observed_timings.items()}
    if set(measured) != set(masks):
        raise ValueError("timings must cover the fixed owner-count calibration masks")
    ratio_masks = masks[1:]
    ratios = []
    for mask in ratio_masks:
        low_seconds, high_seconds = measured[mask]
        if (
            not math.isfinite(low_seconds)
            or not math.isfinite(high_seconds)
            or low_seconds < 0
            or high_seconds <= 0
        ):
            raise ValueError("calibration timings must be finite with positive high time")
        ratios.append(low_seconds / high_seconds)
    q1, median, q3 = np.quantile(np.asarray(ratios), [0.25, 0.5, 0.75])
    ratio_views = {"q1": float(q1), "median": float(median), "q3": float(q3)}
    return CostCalibration(
        n_owners=n_owners,
        masks=masks,
        ratio_masks=ratio_masks,
        timings=measured,
        ratio_median=float(median),
        ratio_q1=float(q1),
        ratio_q3=float(q3),
        preprocessing_seconds=float(preprocessing_seconds),
        fixed_high_equivalent={
            name: (1 << n_owners) * ratio for name, ratio in ratio_views.items()
        },
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def _code_hash() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for name in ("real_coalitions.py", "real_models.py", "real_features.py"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _input_hash(
    manifest: RealDatasetManifest,
    features: FeatureArtifact,
    config: ModelTrajectoryConfig,
) -> str:
    payload = {
        "manifest_hash": manifest.content_hash,
        "feature_hash": features.feature_hash,
        "model": asdict(config),
        "code_hash": _code_hash(),
        "probability_epsilon": PROBABILITY_EPSILON,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _record_from_payload(payload: Mapping[str, Any], expected_hash: str) -> RealCoalitionRecord:
    if payload.get("input_hash") != expected_hash:
        raise ValueError("coalition record input hash mismatch")
    utilities = {name: float(value) for name, value in payload["utilities"].items()}
    if set(utilities) != set(FIDELITIES) or any(
        not math.isfinite(value) for value in utilities.values()
    ):
        raise ValueError("invalid coalition utility record")
    return RealCoalitionRecord(
        mask=int(payload["mask"]),
        utilities=utilities,
        fit_seconds=float(payload["fit_seconds"]),
        checkpoint_hashes=dict(payload.get("checkpoint_hashes", {})),
        input_hash=expected_hash,
    )


def _tables_hash(tables: Mapping[str, CoalitionGameTable]) -> str:
    return hashlib.sha256(
        json.dumps(
            {name: tables[name].content_hash for name in FIDELITIES},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def build_real_coalition_tables(
    manifest: RealDatasetManifest,
    features: FeatureArtifact,
    trajectory_config: ModelTrajectoryConfig,
    *,
    cache_dir: Path,
    device: str,
) -> RealCoalitionTables:
    if features.dataset_id != manifest.dataset_id:
        raise ValueError("feature artifact dataset does not match manifest")
    input_hash = _input_hash(manifest, features, trajectory_config)
    root = Path(cache_dir) / input_hash
    marker_path = root / ".complete.json"
    row_index = {row_id: index for index, row_id in enumerate(features.row_ids)}
    evaluation_indices = np.asarray(
        [row_index[row_id] for row_id in manifest.validation_row_ids], dtype=np.int64
    )
    evaluation = features.values[evaluation_indices]
    evaluation_targets = features.targets[evaluation_indices]
    records: dict[int, RealCoalitionRecord] = {}
    trajectory_builds = 0
    for mask in range(1 << manifest.n_owners):
        record_path = root / "coalitions" / f"{mask:04d}.json"
        if record_path.exists():
            records[mask] = _record_from_payload(
                json.loads(record_path.read_text()), input_hash
            )
            continue
        if mask == 0:
            if manifest.task == "classification":
                utilities = {name: 0.0 for name in FIDELITIES}
            else:
                value = regression_utility(np.zeros(len(evaluation_targets)), evaluation_targets)
                utilities = {name: value for name in FIDELITIES}
            record = RealCoalitionRecord(mask, utilities, 0.0, {}, input_hash)
        else:
            selected_rows = []
            for owner in range(manifest.n_owners):
                if mask & (1 << owner):
                    selected_rows.extend(manifest.owner_row_ids[f"o{owner}"])
            train_indices = np.asarray(
                [row_index[row_id] for row_id in selected_rows], dtype=np.int64
            )
            trajectory = build_trajectory(
                trajectory_config,
                (features.values[train_indices], features.targets[train_indices]),
                evaluation,
                seed=manifest.split_seed + mask,
                device=device,
            )
            trajectory_builds += 1
            if manifest.task == "classification":
                class_index = {
                    label: index
                    for index, label in enumerate(trajectory_config.global_classes)
                }
                encoded = np.asarray(
                    [class_index[label] for label in evaluation_targets.tolist()],
                    dtype=np.int64,
                )
                utilities = {
                    name: classification_utility(
                        prediction.values,
                        encoded,
                        n_classes=len(trajectory_config.global_classes),
                    )
                    for name, prediction in trajectory.predictions.items()
                }
            else:
                utilities = {
                    name: regression_utility(prediction.values, evaluation_targets)
                    for name, prediction in trajectory.predictions.items()
                }
            record = RealCoalitionRecord(
                mask,
                utilities,
                trajectory.fit_seconds,
                trajectory.checkpoint_hashes,
                input_hash,
            )
        _atomic_json(record_path, asdict(record))
        records[mask] = record

    if set(records) != set(range(1 << manifest.n_owners)):
        raise ValueError("coalition records are incomplete")
    owner_ids = tuple(f"o{index}" for index in range(manifest.n_owners))
    measured_seconds = sum(record.fit_seconds for record in records.values())
    tables = {
        name: CoalitionGameTable(
            owner_ids,
            {mask: records[mask].utilities[name] for mask in records},
            name,
            measured_seconds=measured_seconds,
            metadata={"input_hash": input_hash, "evidence_scope": "real_trained_game"},
        )
        for name in FIDELITIES
    }
    content_hash = _tables_hash(tables)
    marker = {
        "input_hash": input_hash,
        "coalitions": len(records),
        "table_hashes": {name: table.content_hash for name, table in tables.items()},
        "content_hash": content_hash,
    }
    if marker_path.exists():
        existing = json.loads(marker_path.read_text())
        if existing != marker:
            raise ValueError("complete coalition marker is stale or corrupt")
    else:
        _atomic_json(marker_path, marker)
    return RealCoalitionTables(
        tables=tables,
        records=records,
        input_hash=input_hash,
        content_hash=content_hash,
        trajectory_builds=trajectory_builds,
    )


__all__ = [
    "RealCoalitionRecord",
    "RealCoalitionTables",
    "BudgetApplicability",
    "CostCalibration",
    "build_real_coalition_tables",
    "calibrate_fidelity_cost",
    "calibration_masks",
    "classification_utility",
    "regression_utility",
]
