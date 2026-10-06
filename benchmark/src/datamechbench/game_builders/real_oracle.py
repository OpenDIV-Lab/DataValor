"""Atomic, lazy coalition-trajectory oracle for large real provider games."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

from .real_coalitions import (
    _input_hash,
    classification_utility,
    regression_utility,
)
from .real_data import RealDatasetManifest
from .real_features import FeatureArtifact
from .real_models import ModelTrajectoryConfig, build_trajectory

FIDELITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class CachedTrajectoryRecord:
    mask: int
    input_hash: str
    utilities: Mapping[str, float]
    fit_seconds: float
    checkpoint_hashes: Mapping[str, str]


TrajectoryEvaluator = Callable[
    [int], tuple[Mapping[str, float], float, Mapping[str, str]]
]


class CachedTrajectoryOracle:
    """Evaluate one coalition lazily and cache all fidelity checkpoints."""

    def __init__(
        self,
        *,
        owner_ids: tuple[str, ...],
        input_hash: str,
        cache_dir: Path,
        evaluator: TrajectoryEvaluator,
    ) -> None:
        owners = tuple(map(str, owner_ids))
        if len(owners) < 2 or len(set(owners)) != len(owners):
            raise ValueError("owner_ids must contain at least two unique owners")
        if not input_hash:
            raise ValueError("input_hash must be non-empty")
        self.owner_ids = owners
        self.input_hash = str(input_hash)
        self.cache_dir = Path(cache_dir)
        self.evaluator = evaluator
        self.trajectory_builds = 0
        self.logical_calls = {name: 0 for name in FIDELITIES}

    @property
    def root(self) -> Path:
        return self.cache_dir / self.input_hash / "coalitions"

    def _path(self, mask: int) -> Path:
        return self.root / f"{mask}.json"

    def _record(self, payload: Mapping[str, object]) -> CachedTrajectoryRecord:
        if payload.get("input_hash") != self.input_hash:
            raise ValueError("coalition record input hash mismatch")
        utilities = {
            str(name): float(value)
            for name, value in dict(payload.get("utilities", {})).items()
        }
        if set(utilities) != set(FIDELITIES) or not all(
            math.isfinite(value) for value in utilities.values()
        ):
            raise ValueError("coalition record must contain every finite fidelity")
        fit_seconds = float(payload.get("fit_seconds", float("nan")))
        if not math.isfinite(fit_seconds) or fit_seconds < 0.0:
            raise ValueError("coalition record has invalid fit_seconds")
        return CachedTrajectoryRecord(
            mask=int(payload["mask"]),
            input_hash=self.input_hash,
            utilities=utilities,
            fit_seconds=fit_seconds,
            checkpoint_hashes={
                str(name): str(value)
                for name, value in dict(payload.get("checkpoint_hashes", {})).items()
            },
        )

    def _load_or_build(self, mask: int) -> CachedTrajectoryRecord:
        path = self._path(mask)
        if path.exists():
            record = self._record(json.loads(path.read_text()))
            if record.mask != mask:
                raise ValueError("coalition record mask mismatch")
            return record
        utilities, fit_seconds, checkpoint_hashes = self.evaluator(mask)
        payload = {
            "mask": int(mask),
            "input_hash": self.input_hash,
            "utilities": dict(utilities),
            "fit_seconds": float(fit_seconds),
            "checkpoint_hashes": dict(checkpoint_hashes),
        }
        record = self._record(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        os.replace(temporary, path)
        self.trajectory_builds += 1
        return record

    def value(self, mask: int, fidelity: str) -> float:
        if fidelity not in FIDELITIES:
            raise ValueError(f"unknown fidelity: {fidelity}")
        full_mask = (1 << len(self.owner_ids)) - 1
        if not isinstance(mask, int) or mask < 0 or mask > full_mask:
            raise ValueError("mask lies outside the owner domain")
        record = self._load_or_build(mask)
        self.logical_calls[fidelity] += 1
        return float(record.utilities[fidelity])

    def fidelity(self, name: str) -> Callable[[int], float]:
        if name not in FIDELITIES:
            raise ValueError(f"unknown fidelity: {name}")
        return lambda mask: self.value(mask, name)


def make_real_trajectory_oracle(
    manifest: RealDatasetManifest,
    features: FeatureArtifact,
    trajectory_config: ModelTrajectoryConfig,
    *,
    cache_dir: Path,
    device: str,
) -> CachedTrajectoryOracle:
    """Create a lazy real-data game without enumerating its ``2**n`` coalitions.

    A requested mask trains the declared nested trajectory exactly once.  Its
    low, medium, and high utilities are then stored together, so asking for a
    second fidelity cannot silently trigger a differently seeded fit.
    """
    if features.dataset_id != manifest.dataset_id:
        raise ValueError("feature artifact dataset does not match manifest")
    if trajectory_config.task != manifest.task:
        raise ValueError("trajectory task does not match manifest")

    row_index = {row_id: index for index, row_id in enumerate(features.row_ids)}
    try:
        evaluation_indices = np.asarray(
            [row_index[row_id] for row_id in manifest.validation_row_ids],
            dtype=np.int64,
        )
        owner_indices = {
            f"o{owner}": np.asarray(
                [row_index[row_id] for row_id in manifest.owner_row_ids[f"o{owner}"]],
                dtype=np.int64,
            )
            for owner in range(manifest.n_owners)
        }
    except KeyError as error:
        raise ValueError(f"manifest row is absent from feature artifact: {error}") from error

    evaluation = features.values[evaluation_indices]
    evaluation_targets = features.targets[evaluation_indices]
    encoded_targets: np.ndarray | None = None
    if manifest.task == "classification":
        class_index = {
            label: index for index, label in enumerate(trajectory_config.global_classes)
        }
        try:
            encoded_targets = np.asarray(
                [class_index[label] for label in evaluation_targets.tolist()],
                dtype=np.int64,
            )
        except KeyError as error:
            raise ValueError(f"validation label is absent from global_classes: {error}") from error

    def evaluate(mask: int) -> tuple[Mapping[str, float], float, Mapping[str, str]]:
        if mask == 0:
            if manifest.task == "classification":
                utilities = {name: 0.0 for name in FIDELITIES}
            else:
                empty_value = regression_utility(
                    np.zeros(len(evaluation_targets)), evaluation_targets
                )
                utilities = {name: empty_value for name in FIDELITIES}
            return utilities, 0.0, {}

        selected = [
            owner_indices[f"o{owner}"]
            for owner in range(manifest.n_owners)
            if mask & (1 << owner)
        ]
        train_indices = np.concatenate(selected)
        trajectory = build_trajectory(
            trajectory_config,
            (features.values[train_indices], features.targets[train_indices]),
            evaluation,
            seed=manifest.split_seed + mask,
            device=device,
        )
        if manifest.task == "classification":
            assert encoded_targets is not None
            utilities = {
                name: classification_utility(
                    prediction.values,
                    encoded_targets,
                    n_classes=len(trajectory_config.global_classes),
                )
                for name, prediction in trajectory.predictions.items()
            }
        else:
            utilities = {
                name: regression_utility(prediction.values, evaluation_targets)
                for name, prediction in trajectory.predictions.items()
            }
        return utilities, trajectory.fit_seconds, trajectory.checkpoint_hashes

    return CachedTrajectoryOracle(
        owner_ids=tuple(f"o{owner}" for owner in range(manifest.n_owners)),
        input_hash=_input_hash(manifest, features, trajectory_config),
        cache_dir=cache_dir,
        evaluator=evaluate,
    )


__all__ = [
    "CachedTrajectoryOracle",
    "CachedTrajectoryRecord",
    "FIDELITIES",
    "make_real_trajectory_oracle",
]
