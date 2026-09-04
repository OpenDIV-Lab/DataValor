"""Small, transparent utility functions for tabular task valuation.

The utility layer deliberately returns task performance units (a bounded
utility score), not money.  A valuator may later map that score to a buyer
specific monetary estimate using costs, rights and budget context.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datavalor.core import ComponentSpec, DataProduct, RunContext, TaskContext

from .interfaces import UtilityFunction


class TabularTaskUtility(UtilityFunction):
    """Score a selected set of tabular records with explainable components.

    ``records`` maps stable unit IDs to dictionaries.  The default score is a
    weighted blend of coverage, category diversity, label balance and
    freshness.  Every component is in ``[0, 1]`` and weights are normalized,
    making the result suitable for LOO/Shapley without hiding assumptions.
    """

    def __init__(
        self,
        records: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        label_field: str = "label",
        group_field: str = "segment",
        freshness_field: str = "fresh",
        target_size: int = 4,
        weights: Mapping[str, float] | None = None,
    ) -> None:
        self.records = {str(key): dict(value) for key, value in (records or {}).items()}
        self.label_field = label_field
        self.group_field = group_field
        self.freshness_field = freshness_field
        self.target_size = max(1, int(target_size))
        self.weights = dict(weights or {"coverage": 0.55, "diversity": 0.20, "balance": 0.15, "freshness": 0.10})

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            "utility.tabular_task",
            "1.0.0",
            "data_value",
            "utility_function",
            capabilities=("coverage", "diversity", "balance", "freshness"),
        )

    def score(self, product: DataProduct, selection: tuple[str, ...], task: TaskContext, context: RunContext) -> float:
        del product, task, context
        rows = [self.records[item] for item in selection if item in self.records]
        if not rows:
            return 0.0
        components = self.components(rows)
        denominator = sum(abs(float(value)) for value in self.weights.values())
        if denominator == 0:
            return 0.0
        score = sum(float(self.weights.get(name, 0.0)) * components.get(name, 0.0) for name in components) / denominator
        return max(0.0, min(1.0, score))

    def components(self, rows: list[Mapping[str, Any]]) -> dict[str, float]:
        coverage = min(1.0, len(rows) / self.target_size)
        groups = {str(row[self.group_field]) for row in rows if row.get(self.group_field) is not None}
        diversity = min(1.0, len(groups) / 2.0)
        labels = [row.get(self.label_field) for row in rows if row.get(self.label_field) is not None]
        balance = 1.0
        if labels:
            positives = sum(float(value) for value in labels) / len(labels)
            balance = max(0.0, 1.0 - abs(positives - 0.5) * 2.0)
        fresh = [float(row[self.freshness_field]) for row in rows if _finite_number(row.get(self.freshness_field))]
        freshness = sum(fresh) / len(fresh) if fresh else 0.0
        return {"coverage": coverage, "diversity": diversity, "balance": balance, "freshness": max(0.0, min(1.0, freshness))}


def _finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and abs(number) != float("inf")


__all__ = ["TabularTaskUtility"]
