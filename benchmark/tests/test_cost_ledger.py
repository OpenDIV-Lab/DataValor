from __future__ import annotations

import pytest
from datamechbench.cost_ledger import EvaluationCostLedger


def test_ledger_keeps_logical_physical_wall_and_gpu_cost_separate() -> None:
    ledger = EvaluationCostLedger(low_cost_ratio=0.1, equivalent_budget=7.0)
    ledger.record(
        "low",
        logical_calls=16,
        physical_calls=4,
        evaluation_seconds=2.0,
        gpu_seconds=1.5,
        preprocessing_seconds=0.4,
        fixed_cost_seconds=0.2,
    )
    ledger.record(
        "high",
        logical_calls=8,
        physical_calls=6,
        evaluation_seconds=5.0,
        gpu_seconds=4.0,
    )

    snapshot = ledger.snapshot()
    assert snapshot["low_logical_calls"] == 16
    assert snapshot["low_physical_calls"] == 4
    assert snapshot["high_logical_calls"] == 8
    assert snapshot["high_physical_calls"] == 6
    assert snapshot["equivalent_high_calls"] == pytest.approx(6.4)
    assert snapshot["evaluation_seconds"] == pytest.approx(7.0)
    assert snapshot["gpu_seconds"] == pytest.approx(5.5)
    assert snapshot["preprocessing_seconds"] == pytest.approx(0.4)
    assert snapshot["fixed_cost_seconds"] == pytest.approx(0.2)
    ledger.assert_within_budget()


def test_ledger_rejects_inferred_counts_and_overspend() -> None:
    ledger = EvaluationCostLedger(low_cost_ratio=0.25, equivalent_budget=2.0)
    with pytest.raises(ValueError, match="physical_calls"):
        ledger.record("low", logical_calls=1, physical_calls=None, evaluation_seconds=0.1)
    with pytest.raises(ValueError, match="cannot exceed logical"):
        ledger.record("high", logical_calls=1, physical_calls=2, evaluation_seconds=0.1)

    ledger.record("high", logical_calls=3, physical_calls=3, evaluation_seconds=0.1)
    with pytest.raises(RuntimeError, match="exceeded"):
        ledger.assert_within_budget()
