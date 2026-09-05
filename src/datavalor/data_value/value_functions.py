"""Advanced, dependency-free valuation functions for stage 3.

The functions in this module deliberately keep three concepts separate:
task utility is a feature, a valuation model maps features to a value estimate,
and a contribution report explains how a total is distributed across units.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Sequence
from typing import Any

from datavalor.core import ComponentSpec, RunContext

from .interfaces import DataValuator, TrainableValuator
from .models import TrainingReport, ValuationMode, ValuationReport, ValuationRequest, ValueEstimate


def _features(request: ValuationRequest) -> dict[str, float]:
    raw = request.options.get("evaluation_vector", {})
    values = {str(key): float(value) for key, value in raw.items() if _finite(value)}
    if request.buyer is not None:
        values.setdefault("buyer_multiplier", float(request.buyer.preferences.get("value_multiplier", 1.0)))
    values.setdefault("adoption_cost", float(request.costs.adoption or 0.0) if request.costs and request.costs.adoption is not None else 0.0)
    return values


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class SymbolicValuator(DataValuator):
    """Evaluate a constrained arithmetic expression over valuation features.

    Only numeric constants, feature names, and ``+ - * / **`` are accepted;
    calls, attributes, subscripting and arbitrary Python execution are
    rejected.  This provides a useful symbolic baseline without adding a
    third-party expression engine or an unsafe ``eval`` call.
    """

    def __init__(self, expression: str = "base_value * quality - adoption_cost", *, base_value: float = 1000.0, currency: str = "CNY") -> None:
        self.expression, self.base_value, self.currency = expression, float(base_value), currency
        self._tree = ast.parse(expression, mode="eval")
        self._validate(self._tree)

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.symbolic", "1.0.0", "data_value", "valuator", capabilities=("symbolic", "explainable"))

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        features = {"base_value": self.base_value, **_features(request)}
        features.setdefault("quality", 0.0)
        value = max(0.0, self._evaluate(self._tree.body, features))
        estimates = tuple(ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency, components=features, explanation={"expression": self.expression}) for target in request.targets)
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.TASK_SPECIFIC, estimates, buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, diagnostics={"run_id": context.run_id, "expression": self.expression})

    @classmethod
    def _validate(cls, node: ast.AST) -> None:
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load)
        if not isinstance(node, allowed):
            raise ValueError(f"unsupported symbolic expression node: {type(node).__name__}")
        for child in ast.iter_child_nodes(node):
            cls._validate(child)
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float)) or not math.isfinite(float(node.value))):
            raise ValueError("symbolic constants must be finite numbers")

    @classmethod
    def _evaluate(cls, node: ast.AST, variables: dict[str, float]) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"symbolic variable {node.id!r} is not provided")
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp):
            value = cls._evaluate(node.operand, variables)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = cls._evaluate(node.left, variables), cls._evaluate(node.right, variables)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right if right else 0.0
            if isinstance(node.op, ast.Pow): return left ** max(-10.0, min(10.0, right))
        raise ValueError(f"cannot evaluate symbolic node: {type(node).__name__}")


class LearnedLinearValuator(TrainableValuator):
    """Fit a small ridge-regularized linear model using only the stdlib."""

    def __init__(self, feature_names: Sequence[str] | None = None, *, ridge: float = 1e-6, currency: str = "CNY") -> None:
        self.feature_names = tuple(feature_names or ("quality", "uniqueness", "buyer_multiplier"))
        self.ridge, self.currency = max(0.0, float(ridge)), currency
        self.intercept = 0.0
        self.coefficients = {name: 0.0 for name in self.feature_names}
        self.fitted = False

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("valuation.learned_linear", "1.0.0", "data_value", "trainable_valuator", capabilities=("fit", "linear", "uncertainty"))

    def fit(self, requests: Sequence[ValuationRequest], observed_values: Sequence[float], context: RunContext) -> TrainingReport:
        if len(requests) != len(observed_values) or not requests:
            raise ValueError("requests and observed_values must be non-empty and have equal length")
        matrix = [[1.0] + [_features(request).get(name, 0.0) for name in self.feature_names] for request in requests]
        targets = [float(value) for value in observed_values]
        gram = [[sum(row[i] * row[j] for row in matrix) + (self.ridge if i == j and i else 0.0) for j in range(len(matrix[0]))] for i in range(len(matrix[0]))]
        rhs = [sum(row[i] * target for row, target in zip(matrix, targets)) for i in range(len(matrix[0]))]
        solution = _solve_linear_system(gram, rhs)
        self.intercept = solution[0]
        self.coefficients = dict(zip(self.feature_names, solution[1:]))
        self.fitted = True
        predictions = [self.intercept + sum(self.coefficients[name] * _features(request).get(name, 0.0) for name in self.feature_names) for request in requests]
        rmse = math.sqrt(sum((prediction - target) ** 2 for prediction, target in zip(predictions, targets)) / len(targets))
        return TrainingReport(self.spec.name, len(requests), converged=True, diagnostics={"run_id": context.run_id, "features": self.feature_names, "ridge": self.ridge, "rmse": rmse})

    def value(self, request: ValuationRequest, context: RunContext) -> ValuationReport:
        if not self.fitted:
            raise RuntimeError("LearnedLinearValuator must be fitted before value()")
        features = _features(request)
        value = max(0.0, self.intercept + sum(self.coefficients[name] * features.get(name, 0.0) for name in self.feature_names))
        estimate = tuple(ValueEstimate(target.target_id, round(value, 6), "monetary", self.currency, components={"intercept": self.intercept, **self.coefficients}, explanation={"features": features}, diagnostics={"fitted": self.fitted}) for target in request.targets)
        return ValuationReport(request.product.product_id, self.spec.name, ValuationMode.MODEL_DEPENDENT, estimate, buyer_id=request.buyer.actor_id if request.buyer else None, task_id=request.task.task_id if request.task else context.task_id, converged=self.fitted, diagnostics={"run_id": context.run_id, "feature_names": self.feature_names})


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with pivoting for the tiny normal equations."""
    n = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("linear valuation features are rank deficient")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(n):
            if row == column: continue
            factor = augmented[row][column]
            augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column])]
    return [augmented[index][-1] for index in range(n)]


__all__ = ["LearnedLinearValuator", "SymbolicValuator"]
