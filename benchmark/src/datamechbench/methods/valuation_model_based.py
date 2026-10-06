"""Model/data-specific valuation methods aggregated to data owners."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from math import factorial
from typing import Any

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import BaggingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from ..data import OwnerDataset
from ..models import ValuationCase, ValuationOutput


def _dataset(case: ValuationCase) -> OwnerDataset:
    dataset = case.metadata.get("owner_dataset")
    if not isinstance(dataset, OwnerDataset):
        raise ValueError("model-based valuation requires owner_dataset metadata")
    return dataset


def _owner_sum(dataset: OwnerDataset, point_values: np.ndarray) -> dict[str, float]:
    return {
        owner: float(np.sum(point_values[np.asarray(rows, dtype=int)]))
        for owner, rows in dataset.owner_rows.items()
    }


def _volume(matrix: np.ndarray) -> float:
    if len(matrix) == 0:
        return 0.0
    gram = matrix.T @ matrix
    determinant = float(np.linalg.det(gram))
    return float(np.sqrt(max(0.0, determinant) + 1e-8))


def _robust_volume_details(
    matrix: np.ndarray, omega: float
) -> tuple[float, dict[str, float | int]]:
    if len(matrix) == 0:
        return 0.0, {
            "compressed_point_count": 0,
            "density_alpha": 0.0,
            "base_volume": 0.0,
            "density_multiplier": 1.0,
        }
    if omega <= 0:
        raise ValueError("omega must be positive")
    origin = np.min(matrix, axis=0)
    cube_ids = np.floor((matrix - origin) / omega).astype(np.int64)
    groups: dict[tuple[int, ...], list[np.ndarray]] = {}
    for cube, row in zip(cube_ids, matrix, strict=True):
        groups.setdefault(tuple(int(value) for value in cube), []).append(row)
    compressed = np.asarray(
        [np.mean(groups[cube], axis=0) for cube in sorted(groups)], dtype=float
    )
    alpha = 1.0 / (10.0 * len(compressed))
    density = 1.0
    for rows in groups.values():
        count = len(rows)
        density *= (1.0 - alpha ** (count + 1)) / (1.0 - alpha)
    base_volume = _volume(compressed)
    return base_volume * density, {
        "compressed_point_count": len(compressed),
        "density_alpha": alpha,
        "base_volume": base_volume,
        "density_multiplier": density,
    }


def _robust_volume(matrix: np.ndarray, omega: float) -> float:
    value, _ = _robust_volume_details(matrix, omega)
    return value


def _volume_features(
    dataset: OwnerDataset, params: Mapping[str, Any], seed: int
) -> np.ndarray:
    features = np.asarray(dataset.x_train, dtype=float)
    if bool(params.get("standardize", True)):
        features = StandardScaler().fit_transform(features)
    requested = int(params.get("pca_components", -1))
    if requested < 0:
        requested = min(6, features.shape[1], max(1, len(features) - 1))
    if requested:
        if requested > min(features.shape):
            raise ValueError("pca_components exceeds the available matrix rank bound")
        features = PCA(n_components=requested, random_state=seed).fit_transform(features)
    return np.asarray(features, dtype=float)


def _volume_shapley(
    method_id: str,
    case: ValuationCase,
    params: Mapping[str, Any],
    seed: int,
) -> ValuationOutput:
    dataset = _dataset(case)
    features = _volume_features(dataset, params, seed)
    owners = tuple(case.owner_ids)
    omega = float(params.get("omega", 0.1))
    robust = method_id == "robust_volume_shapley"
    cache: dict[frozenset[str], float] = {frozenset(): 0.0}

    def characteristic(coalition: frozenset[str]) -> float:
        if coalition in cache:
            return cache[coalition]
        rows = [row for owner in owners if owner in coalition for row in dataset.owner_rows[owner]]
        matrix = features[np.asarray(rows, dtype=int)]
        value = _robust_volume(matrix, omega) if robust else _volume(matrix)
        cache[coalition] = value
        return value

    count = len(owners)
    denominator = factorial(count)
    scores: dict[str, float] = {}
    for owner in owners:
        others = tuple(item for item in owners if item != owner)
        contribution = 0.0
        for size in range(len(others) + 1):
            weight = factorial(size) * factorial(count - size - 1) / denominator
            for subset in combinations(others, size):
                coalition = frozenset(subset)
                contribution += weight * (
                    characteristic(coalition | {owner}) - characteristic(coalition)
                )
        scores[owner] = float(contribution)
    grand_coalition = frozenset(owners)
    grand = characteristic(grand_coalition)
    robust_diagnostics: dict[str, float | int] = {}
    if robust:
        grand_rows = [row for owner in owners for row in dataset.owner_rows[owner]]
        _, robust_diagnostics = _robust_volume_details(
            features[np.asarray(grand_rows, dtype=int)], omega
        )
    return ValuationOutput(
        scores,
        diagnostics={
            "characteristic": "robust_volume" if robust else "volume",
            "characteristic_value": grand,
            "omega": omega if robust else None,
            "standardized": bool(params.get("standardize", True)),
            "feature_dimension": int(features.shape[1]),
            "shapley_enumeration": "exact_subsets",
            "owner_aggregation": "group_characteristic",
            **robust_diagnostics,
        },
        utility_calls=len(cache),
    )


def _knn_shapley(
    case: ValuationCase, params: Mapping[str, Any], seed: int
) -> ValuationOutput:
    del seed
    dataset = _dataset(case)
    scaler = StandardScaler().fit(dataset.x_train)
    x_train = scaler.transform(dataset.x_train)
    x_valid = scaler.transform(dataset.x_validation)
    n = len(x_train)
    k = min(max(1, int(params.get("k", 5))), n)
    values = np.zeros(n, dtype=float)
    for x_value, label in zip(x_valid, dataset.y_validation, strict=True):
        distances = np.sum((x_train - x_value) ** 2, axis=1)
        order = np.argsort(distances, kind="stable")
        ordered_labels = dataset.y_train[order]
        contribution = np.zeros(n, dtype=float)
        contribution[-1] = float(ordered_labels[-1] == label) / n
        for rank in range(n - 2, -1, -1):
            weight = min(k, rank + 1) / (k * (rank + 1))
            contribution[rank] = contribution[rank + 1] + weight * (
                float(ordered_labels[rank] == label)
                - float(ordered_labels[rank + 1] == label)
            )
        values[order] += contribution
    values /= len(x_valid)
    return ValuationOutput(
        _owner_sum(dataset, values),
        diagnostics={"k": k, "validation_rows": len(x_valid)},
        utility_calls=0,
    )


def _data_oob(
    case: ValuationCase, params: Mapping[str, Any], seed: int
) -> ValuationOutput:
    dataset = _dataset(case)
    estimators = int(params.get("n_estimators", 64))
    bagging = BaggingClassifier(
        estimator=DecisionTreeClassifier(max_depth=None, random_state=seed),
        n_estimators=estimators,
        bootstrap=True,
        random_state=seed,
        n_jobs=1,
    )
    bagging.fit(dataset.x_train, dataset.y_train)
    totals = np.zeros(len(dataset.x_train), dtype=float)
    counts = np.zeros(len(dataset.x_train), dtype=int)
    all_rows = np.arange(len(dataset.x_train))
    for estimator, sampled in zip(
        bagging.estimators_, bagging.estimators_samples_, strict=True
    ):
        oob = np.setdiff1d(all_rows, np.unique(sampled), assume_unique=False)
        if len(oob) == 0:
            continue
        correct = estimator.predict(dataset.x_train[oob]) == dataset.y_train[oob]
        totals[oob] += correct.astype(float)
        counts[oob] += 1
    point_values = np.divide(
        totals,
        counts,
        out=np.full_like(totals, 0.5),
        where=counts > 0,
    )
    return ValuationOutput(
        _owner_sum(dataset, point_values),
        diagnostics={
            "n_estimators": estimators,
            "minimum_oob_votes": int(counts.min()),
            "owner_aggregation": "sum",
        },
        utility_calls=0,
    )


def _influence(
    case: ValuationCase, params: Mapping[str, Any], seed: int
) -> ValuationOutput:
    dataset = _dataset(case)
    scaler = StandardScaler().fit(dataset.x_train)
    x_train = scaler.transform(dataset.x_train)
    x_valid = scaler.transform(dataset.x_validation)
    model = LogisticRegression(
        C=float(params.get("c", 1.0)), max_iter=3000, random_state=seed
    ).fit(x_train, dataset.y_train)
    train_augmented = np.column_stack((x_train, np.ones(len(x_train))))
    valid_augmented = np.column_stack((x_valid, np.ones(len(x_valid))))
    train_prob = model.predict_proba(x_train)[:, 1]
    valid_prob = model.predict_proba(x_valid)[:, 1]
    train_gradients = (train_prob - dataset.y_train)[:, None] * train_augmented
    valid_gradient = np.mean(
        (valid_prob - dataset.y_validation)[:, None] * valid_augmented, axis=0
    )
    weights = train_prob * (1.0 - train_prob)
    hessian = (train_augmented.T * weights) @ train_augmented / len(x_train)
    regularization = 1.0 / (float(params.get("c", 1.0)) * len(x_train))
    hessian += np.diag([regularization] * x_train.shape[1] + [1e-8])
    direction = np.linalg.solve(hessian + np.eye(hessian.shape[0]) * 1e-8, valid_gradient)
    point_values = train_gradients @ direction / len(x_train)
    return ValuationOutput(
        _owner_sum(dataset, point_values),
        diagnostics={
            "model": "logistic_regression",
            "hessian_dimension": len(direction),
            "score_semantics": "positive_is_helpful",
            "owner_aggregation": "sum",
        },
        utility_calls=0,
    )


def _logistic_gradients(
    case: ValuationCase, params: Mapping[str, Any], seed: int
) -> tuple[OwnerDataset, np.ndarray, np.ndarray]:
    """Return per-example and mean validation gradients for multinomial log loss."""

    dataset = _dataset(case)
    scaler = StandardScaler().fit(dataset.x_train)
    x_train = scaler.transform(dataset.x_train)
    x_valid = scaler.transform(dataset.x_validation)
    model = LogisticRegression(
        C=float(params.get("c", 1.0)), max_iter=3000, random_state=seed
    ).fit(x_train, dataset.y_train)
    classes = model.classes_

    def gradients(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        augmented = np.column_stack((x, np.ones(len(x))))
        probabilities = model.predict_proba(x)
        target = np.equal(y[:, None], classes[None, :]).astype(float)
        return np.einsum("nc,nd->ncd", probabilities - target, augmented).reshape(len(x), -1)

    return dataset, gradients(x_train, dataset.y_train), np.mean(
        gradients(x_valid, dataset.y_validation), axis=0
    )


def _gradient_attribution(
    method_id: str, case: ValuationCase, params: Mapping[str, Any], seed: int
) -> ValuationOutput:
    dataset, train_gradients, validation_gradient = _logistic_gradients(case, params, seed)
    if method_id == "tracin_cp":
        point_values = train_gradients @ validation_gradient
        estimator = "single-checkpoint TracInCP gradient dot product"
    elif method_id == "gradient_cosine":
        denominator = np.linalg.norm(train_gradients, axis=1) * np.linalg.norm(validation_gradient)
        point_values = np.divide(
            train_gradients @ validation_gradient,
            denominator,
            out=np.zeros(len(train_gradients)),
            where=denominator > 0,
        )
        estimator = "dattri Grad-Cos"
    elif method_id == "datainf":
        damping = float(params.get("damping", 1e-3))
        diagonal_fisher = np.mean(train_gradients**2, axis=0) + damping
        point_values = train_gradients @ (validation_gradient / diagonal_fisher)
        estimator = "DataInf diagonal empirical-Fisher inverse"
    else:
        raise KeyError(method_id)
    return ValuationOutput(
        _owner_sum(dataset, point_values),
        diagnostics={
            "estimator": estimator,
            "checkpoint_count": 1,
            "owner_aggregation": "sum",
            "score_semantics": "positive_is_helpful",
        },
        utility_calls=0,
    )


def evaluate_model_based(
    method_id: str,
    case: ValuationCase,
    params: Mapping[str, Any],
    seed: int,
) -> ValuationOutput:
    if method_id == "knn_shapley":
        return _knn_shapley(case, params, seed)
    if method_id == "data_oob":
        return _data_oob(case, params, seed)
    if method_id in {"volume_shapley", "robust_volume_shapley"}:
        return _volume_shapley(method_id, case, params, seed)
    if method_id == "influence_function":
        return _influence(case, params, seed)
    if method_id in {"tracin_cp", "gradient_cosine", "datainf"}:
        return _gradient_attribution(method_id, case, params, seed)
    raise KeyError(f"unknown model-based valuation method: {method_id}")


__all__ = ["evaluate_model_based"]
