"""Dependency-free task metrics used by model-dependent valuation.

These functions intentionally operate on already separated evaluation arrays;
data loading and model training stay with the caller or a task adapter.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def classification_scores(y_true: Sequence[Any], y_pred: Sequence[Any], *, positive_label: Any = 1) -> dict[str, float | int]:
    """Return accuracy, balanced accuracy, precision, recall and F1."""
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must be non-empty and have equal length")
    labels = sorted(set(y_true) | set(y_pred), key=str)
    correct = sum(a == b for a, b in zip(y_true, y_pred))
    recalls = []
    for label in labels:
        actual = sum(value == label for value in y_true)
        hit = sum(a == b == label for a, b in zip(y_true, y_pred))
        recalls.append(hit / actual if actual else 0.0)
    tp = sum(a == b == positive_label for a, b in zip(y_true, y_pred))
    predicted_positive = sum(value == positive_label for value in y_pred)
    actual_positive = sum(value == positive_label for value in y_true)
    precision = tp / predicted_positive if predicted_positive else 0.0
    recall = tp / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"accuracy": correct / len(y_true), "balanced_accuracy": sum(recalls) / len(recalls), "precision": precision, "recall": recall, "f1": f1, "record_count": len(y_true), "class_count": len(labels), "confusion": {str(label): {str(pred): sum(a == label and b == pred for a, b in zip(y_true, y_pred)) for pred in labels} for label in labels}}


def binary_roc_auc(y_true: Sequence[Any], scores: Sequence[float], *, positive_label: Any = 1) -> float:
    """Compute rank-based binary ROC-AUC with tie averaging."""
    if len(y_true) != len(scores) or not y_true:
        raise ValueError("y_true and scores must be non-empty and have equal length")
    positives = [float(score) for label, score in zip(y_true, scores) if label == positive_label]
    negatives = [float(score) for label, score in zip(y_true, scores) if label != positive_label]
    if not positives or not negatives:
        return 0.5
    wins = sum(1.0 if positive > negative else 0.5 if positive == negative else 0.0 for positive in positives for negative in negatives)
    return wins / (len(positives) * len(negatives))


def regression_scores(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, float | int]:
    """Return MAE, RMSE and R² for a regression evaluation."""
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must be non-empty and have equal length")
    errors = [float(pred) - float(actual) for actual, pred in zip(y_true, y_pred)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mean = sum(float(value) for value in y_true) / len(y_true)
    total = sum((float(value) - mean) ** 2 for value in y_true)
    r2 = 1.0 - sum(error * error for error in errors) / total if total else 0.0
    return {"mae": mae, "rmse": rmse, "r2": r2, "record_count": len(y_true)}


def ranking_scores(relevance: Sequence[float], scores: Sequence[float], *, k: int | None = None) -> dict[str, float | int]:
    """Compute NDCG@k, precision@k and recall@k for one ranked list."""
    if len(relevance) != len(scores) or not relevance:
        raise ValueError("relevance and scores must be non-empty and have equal length")
    limit = min(len(relevance), max(1, k or len(relevance)))
    order = sorted(range(len(scores)), key=lambda index: float(scores[index]), reverse=True)[:limit]
    ideal = sorted((float(value) for value in relevance), reverse=True)[:limit]
    dcg = sum((2 ** float(relevance[index]) - 1) / math.log2(rank + 2) for rank, index in enumerate(order))
    idcg = sum((2 ** value - 1) / math.log2(rank + 2) for rank, value in enumerate(ideal))
    relevant_total = sum(float(value) > 0 for value in relevance)
    hits = sum(float(relevance[index]) > 0 for index in order)
    return {"ndcg": dcg / idcg if idcg else 0.0, "precision_at_k": hits / limit, "recall_at_k": hits / relevant_total if relevant_total else 0.0, "k": limit, "record_count": len(relevance)}


def incremental_gain(baseline: float, candidate: float, *, direction: str = "higher_is_better") -> float:
    """Convert two task scores into a positive-is-improvement gain."""
    if direction not in {"higher_is_better", "lower_is_better"}:
        raise ValueError("direction must be higher_is_better or lower_is_better")
    return float(candidate) - float(baseline) if direction == "higher_is_better" else float(baseline) - float(candidate)


__all__ = ["binary_roc_auc", "classification_scores", "incremental_gain", "ranking_scores", "regression_scores"]
