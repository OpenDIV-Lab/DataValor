"""Strictly nested model trajectories for real coalition games."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from .models import fidelity_ladder


@dataclass(frozen=True)
class ModelTrajectoryConfig:
    model_family: str
    task: str
    global_classes: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if self.task not in {"classification", "regression"}:
            raise ValueError("task must be classification or regression")
        if self.task == "classification" and not self.global_classes:
            raise ValueError("classification trajectories require global_classes")


@dataclass(frozen=True)
class FidelityPrediction:
    name: str
    capacity: int
    values: np.ndarray
    checkpoint_hash: str | None = None


@dataclass(frozen=True)
class NestedTrajectory:
    config: ModelTrajectoryConfig
    predictions: Mapping[str, FidelityPrediction]
    estimator: Any
    fit_seconds: float
    device: str
    checkpoints: Mapping[str, Mapping[str, np.ndarray]] = field(default_factory=dict)
    checkpoint_hashes: Mapping[str, str] = field(default_factory=dict)
    checkpoint_epochs: Mapping[str, int] = field(default_factory=dict)
    physical_gpu_id: int | None = None


class _DegenerateGradientBoostingClassifier:
    """The one-class limit of the declared boosting family."""

    family = "degenerate_gradient_boosting"

    def __init__(self, label: Any, n_estimators: int) -> None:
        self.classes_ = np.asarray([label])
        self.n_estimators = n_estimators

    def staged_predict_proba(self, features: np.ndarray):
        values = np.ones((len(features), 1), dtype=np.float64)
        for _ in range(self.n_estimators):
            yield values.copy()


def _align_probabilities(
    probabilities: np.ndarray,
    local_classes: np.ndarray,
    global_classes: tuple[Any, ...],
) -> np.ndarray:
    aligned = np.zeros((len(probabilities), len(global_classes)), dtype=np.float64)
    global_index = {label: index for index, label in enumerate(global_classes)}
    for local_index, label in enumerate(local_classes.tolist()):
        if label not in global_index:
            raise ValueError(f"training label {label!r} is absent from global_classes")
        aligned[:, global_index[label]] = probabilities[:, local_index]
    return aligned


def _forest_trajectory(
    config: ModelTrajectoryConfig,
    features: np.ndarray,
    targets: np.ndarray,
    evaluation: np.ndarray,
    seed: int,
    max_fidelity: str,
) -> tuple[Any, dict[str, FidelityPrediction]]:
    ladder = fidelity_ladder("tree_ensemble")
    visible_ladder = ladder[: tuple(row.name for row in ladder).index(max_fidelity) + 1]
    high_capacity = visible_ladder[-1].capacity
    if config.task == "classification":
        from sklearn.ensemble import RandomForestClassifier

        estimator = RandomForestClassifier(
            n_estimators=high_capacity,
            random_state=seed,
            n_jobs=1,
        ).fit(features, targets)
        predictions = {}
        for fidelity in visible_ladder:
            local = np.mean(
                [tree.predict_proba(evaluation) for tree in estimator.estimators_[: fidelity.capacity]],
                axis=0,
            )
            values = _align_probabilities(local, estimator.classes_, config.global_classes)
            predictions[fidelity.name] = FidelityPrediction(
                fidelity.name, fidelity.capacity, values
            )
        return estimator, predictions

    from sklearn.ensemble import RandomForestRegressor

    estimator = RandomForestRegressor(
        n_estimators=high_capacity,
        random_state=seed,
        n_jobs=1,
    ).fit(features, targets)
    predictions = {}
    for fidelity in visible_ladder:
        values = np.mean(
            [tree.predict(evaluation) for tree in estimator.estimators_[: fidelity.capacity]],
            axis=0,
        )
        predictions[fidelity.name] = FidelityPrediction(
            fidelity.name, fidelity.capacity, values
        )
    return estimator, predictions


def _boosting_trajectory(
    config: ModelTrajectoryConfig,
    features: np.ndarray,
    targets: np.ndarray,
    evaluation: np.ndarray,
    seed: int,
    max_fidelity: str,
) -> tuple[Any, dict[str, FidelityPrediction]]:
    ladder = fidelity_ladder("boosting")
    visible_ladder = ladder[: tuple(row.name for row in ladder).index(max_fidelity) + 1]
    high_capacity = visible_ladder[-1].capacity
    if config.task == "classification":
        unique_targets = np.unique(targets)
        if len(unique_targets) == 1:
            estimator = _DegenerateGradientBoostingClassifier(
                unique_targets[0], high_capacity
            )
            staged = list(estimator.staged_predict_proba(evaluation))
            predictions = {
                fidelity.name: FidelityPrediction(
                    fidelity.name,
                    fidelity.capacity,
                    _align_probabilities(
                        staged[fidelity.capacity - 1],
                        estimator.classes_,
                        config.global_classes,
                    ),
                )
                for fidelity in visible_ladder
            }
            return estimator, predictions
        from sklearn.ensemble import GradientBoostingClassifier

        estimator = GradientBoostingClassifier(
            n_estimators=high_capacity,
            random_state=seed,
        ).fit(features, targets)
        staged = list(estimator.staged_predict_proba(evaluation))
        predictions = {
            fidelity.name: FidelityPrediction(
                fidelity.name,
                fidelity.capacity,
                _align_probabilities(
                    staged[fidelity.capacity - 1],
                    estimator.classes_,
                    config.global_classes,
                ),
            )
            for fidelity in visible_ladder
        }
        return estimator, predictions

    from sklearn.ensemble import GradientBoostingRegressor

    estimator = GradientBoostingRegressor(
        n_estimators=high_capacity,
        random_state=seed,
    ).fit(features, targets)
    staged = list(estimator.staged_predict(evaluation))
    predictions = {
        fidelity.name: FidelityPrediction(
            fidelity.name,
            fidelity.capacity,
            staged[fidelity.capacity - 1],
        )
        for fidelity in visible_ladder
    }
    return estimator, predictions


def _checkpoint_hash(state: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = np.ascontiguousarray(state[name])
        digest.update(name.encode())
        digest.update(str(value.dtype).encode())
        digest.update(str(value.shape).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def _neural_trajectory(
    config: ModelTrajectoryConfig,
    features: np.ndarray,
    targets: np.ndarray,
    evaluation: np.ndarray,
    seed: int,
    device: str,
    max_fidelity: str,
) -> tuple[
    Any,
    dict[str, FidelityPrediction],
    dict[str, Mapping[str, np.ndarray]],
    dict[str, str],
    dict[str, int],
]:
    import torch

    torch.manual_seed(seed)
    if device.startswith("cuda"):
        torch.cuda.manual_seed_all(seed)
    input_width = int(features.shape[1])
    output_width = len(config.global_classes) if config.task == "classification" else 1
    estimator = torch.nn.Linear(input_width, output_width).to(device)
    optimizer = torch.optim.SGD(estimator.parameters(), lr=0.05)
    train_features = torch.as_tensor(features, dtype=torch.float32, device=device)
    evaluation_features = torch.as_tensor(
        evaluation, dtype=torch.float32, device=device
    )
    if config.task == "classification":
        class_index = {label: index for index, label in enumerate(config.global_classes)}
        try:
            encoded_targets = np.asarray(
                [class_index[label] for label in targets.tolist()], dtype=np.int64
            )
        except KeyError as exc:
            raise ValueError(f"training label {exc.args[0]!r} is absent from global_classes") from exc
        train_targets = torch.as_tensor(encoded_targets, dtype=torch.long, device=device)
        loss_function = torch.nn.CrossEntropyLoss()
    else:
        train_targets = torch.as_tensor(
            targets, dtype=torch.float32, device=device
        ).reshape(-1, 1)
        loss_function = torch.nn.MSELoss()

    ladder = fidelity_ladder("neural_head")
    visible_ladder = ladder[: tuple(row.name for row in ladder).index(max_fidelity) + 1]
    by_epoch = {fidelity.capacity: fidelity for fidelity in visible_ladder}
    predictions: dict[str, FidelityPrediction] = {}
    checkpoints: dict[str, Mapping[str, np.ndarray]] = {}
    checkpoint_hashes: dict[str, str] = {}
    checkpoint_epochs: dict[str, int] = {}
    for epoch in range(1, visible_ladder[-1].capacity + 1):
        estimator.train()
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(estimator(train_features), train_targets)
        loss.backward()
        optimizer.step()
        if epoch not in by_epoch:
            continue
        fidelity = by_epoch[epoch]
        state = {
            name: value.detach().cpu().numpy().copy()
            for name, value in estimator.state_dict().items()
        }
        state_hash = _checkpoint_hash(state)
        estimator.eval()
        with torch.no_grad():
            output = estimator(evaluation_features)
            if config.task == "classification":
                output = torch.softmax(output, dim=1)
            else:
                output = output[:, 0]
        values = output.detach().cpu().numpy()
        checkpoints[fidelity.name] = state
        checkpoint_hashes[fidelity.name] = state_hash
        checkpoint_epochs[fidelity.name] = epoch
        predictions[fidelity.name] = FidelityPrediction(
            fidelity.name,
            fidelity.capacity,
            values,
            checkpoint_hash=state_hash,
        )
    return estimator, predictions, checkpoints, checkpoint_hashes, checkpoint_epochs


def build_trajectory(
    config: ModelTrajectoryConfig,
    train: tuple[Any, Any],
    evaluation: Any,
    *,
    seed: int,
    device: str,
    max_fidelity: str = "high",
) -> NestedTrajectory:
    """Fit through ``max_fidelity`` and expose its exact nested prefixes."""
    if max_fidelity not in {"low", "medium", "high"}:
        raise ValueError("max_fidelity must be low, medium, or high")
    if device != "cpu" and config.model_family != "neural_head":
        raise ValueError("tree and boosting trajectories run deterministically on cpu")
    features, targets = (np.asarray(train[0]), np.asarray(train[1]))
    evaluation_array = np.asarray(evaluation)
    started = time.perf_counter()
    checkpoints: dict[str, Mapping[str, np.ndarray]] = {}
    checkpoint_hashes: dict[str, str] = {}
    checkpoint_epochs: dict[str, int] = {}
    if config.model_family == "tree_ensemble":
        estimator, predictions = _forest_trajectory(
            config, features, targets, evaluation_array, seed, max_fidelity
        )
    elif config.model_family == "boosting":
        estimator, predictions = _boosting_trajectory(
            config, features, targets, evaluation_array, seed, max_fidelity
        )
    elif config.model_family == "neural_head":
        (
            estimator,
            predictions,
            checkpoints,
            checkpoint_hashes,
            checkpoint_epochs,
        ) = _neural_trajectory(
            config, features, targets, evaluation_array, seed, device, max_fidelity
        )
    else:
        raise ValueError(f"unsupported model family: {config.model_family}")
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    physical_gpu_id = None
    if device.startswith("cuda") and visible_devices:
        physical_gpu_id = int(visible_devices.split(",")[0])
    return NestedTrajectory(
        config=config,
        predictions=predictions,
        estimator=estimator,
        fit_seconds=time.perf_counter() - started,
        device=device,
        checkpoints=checkpoints,
        checkpoint_hashes=checkpoint_hashes,
        checkpoint_epochs=checkpoint_epochs,
        physical_gpu_id=physical_gpu_id,
    )


__all__ = [
    "FidelityPrediction",
    "ModelTrajectoryConfig",
    "NestedTrajectory",
    "build_trajectory",
]
