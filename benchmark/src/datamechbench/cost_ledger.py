"""Explicit accounting for cached multi-fidelity benchmark evaluations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationCostLedger:
    """Record observed costs without reconstructing them from algorithm output."""

    low_cost_ratio: float
    equivalent_budget: float | None = None
    low_cost_ratio_q1: float | None = None
    low_cost_ratio_q3: float | None = None
    _totals: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.low_cost_ratio) or self.low_cost_ratio < 0:
            raise ValueError("low_cost_ratio must be finite and non-negative")
        if self.equivalent_budget is not None and (
            not math.isfinite(self.equivalent_budget) or self.equivalent_budget < 0
        ):
            raise ValueError("equivalent_budget must be finite and non-negative")
        for value in (self.low_cost_ratio_q1, self.low_cost_ratio_q3):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("cost-ratio quartiles must be finite and non-negative")
        self._totals = {
            "low_logical_calls": 0,
            "low_physical_calls": 0,
            "high_logical_calls": 0,
            "high_physical_calls": 0,
            "evaluation_seconds": 0.0,
            "gpu_seconds": 0.0,
            "preprocessing_seconds": 0.0,
            "fixed_cost_seconds": 0.0,
        }

    def record(
        self,
        fidelity: str,
        *,
        logical_calls: int,
        physical_calls: int | None,
        evaluation_seconds: float,
        gpu_seconds: float = 0.0,
        preprocessing_seconds: float = 0.0,
        fixed_cost_seconds: float = 0.0,
    ) -> None:
        if fidelity not in {"low", "high"}:
            raise ValueError("fidelity must be 'low' or 'high'")
        if physical_calls is None:
            raise ValueError("physical_calls must be measured explicitly")
        if not isinstance(logical_calls, int) or not isinstance(physical_calls, int):
            raise TypeError("call counts must be integers")
        if logical_calls < 0 or physical_calls < 0:
            raise ValueError("call counts must be non-negative")
        if physical_calls > logical_calls:
            raise ValueError("physical_calls cannot exceed logical_calls")
        timings = {
            "evaluation_seconds": evaluation_seconds,
            "gpu_seconds": gpu_seconds,
            "preprocessing_seconds": preprocessing_seconds,
            "fixed_cost_seconds": fixed_cost_seconds,
        }
        if any(not math.isfinite(value) or value < 0 for value in timings.values()):
            raise ValueError("timings must be finite and non-negative")
        self._totals[f"{fidelity}_logical_calls"] += logical_calls
        self._totals[f"{fidelity}_physical_calls"] += physical_calls
        for key, value in timings.items():
            self._totals[key] += value

    @property
    def equivalent_high_calls(self) -> float:
        return (
            self._totals["high_physical_calls"]
            + self.low_cost_ratio * self._totals["low_physical_calls"]
        )

    def _equivalent_high_calls_at(self, ratio: float | None) -> float | None:
        if ratio is None:
            return None
        return self._totals["high_physical_calls"] + ratio * self._totals[
            "low_physical_calls"
        ]

    def assert_within_budget(self, budget: float | None = None) -> None:
        limit = self.equivalent_budget if budget is None else budget
        if limit is None:
            raise ValueError("no equivalent budget was supplied")
        if self.equivalent_high_calls > limit + 1e-12:
            raise RuntimeError(
                f"equivalent evaluation budget exceeded: {self.equivalent_high_calls} > {limit}"
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            **self._totals,
            "low_cost_ratio": self.low_cost_ratio,
            "equivalent_budget": self.equivalent_budget,
            "equivalent_high_calls": self.equivalent_high_calls,
            "low_cost_ratio_q1": self.low_cost_ratio_q1,
            "low_cost_ratio_q3": self.low_cost_ratio_q3,
            "equivalent_high_calls_q1": self._equivalent_high_calls_at(
                self.low_cost_ratio_q1
            ),
            "equivalent_high_calls_q3": self._equivalent_high_calls_at(
                self.low_cost_ratio_q3
            ),
        }


__all__ = ["EvaluationCostLedger"]
