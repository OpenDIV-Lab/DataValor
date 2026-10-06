from __future__ import annotations

import pytest
from datamechbench.cost_ledger import EvaluationCostLedger
from datamechbench.game_builders.real_coalitions import (
    calibrate_fidelity_cost,
    calibration_masks,
)


def test_calibration_masks_cover_empty_singleton_half_and_full_by_owner_count() -> None:
    assert calibration_masks(8) == (0, 1, 15, 255)
    assert calibration_masks(10) == (0, 1, 31, 1023)


def test_calibration_excludes_empty_predictor_and_reports_median_iqr() -> None:
    calibration = calibrate_fidelity_cost(
        n_owners=8,
        observed_timings={
            0: (0.0, 0.0),
            1: (1.0, 10.0),
            15: (2.0, 10.0),
            255: (4.0, 10.0),
        },
        preprocessing_seconds=7.5,
    )
    assert calibration.ratio_median == pytest.approx(0.2)
    assert calibration.ratio_q1 == pytest.approx(0.15)
    assert calibration.ratio_q3 == pytest.approx(0.3)
    assert calibration.ratio_masks == (1, 15, 255)
    assert calibration.preprocessing_seconds == pytest.approx(7.5)
    assert calibration.fixed_high_equivalent["median"] == pytest.approx(51.2)
    status = calibration.budget_status(40)
    assert status.applicable is False
    assert status.reason == "fixed_low_table_cost_exceeds_budget"
    assert status.spent == 0.0


def test_cost_ledger_exposes_median_and_iqr_accounting_views() -> None:
    ledger = EvaluationCostLedger(
        low_cost_ratio=0.2,
        low_cost_ratio_q1=0.15,
        low_cost_ratio_q3=0.3,
        equivalent_budget=10,
    )
    ledger.record("low", logical_calls=5, physical_calls=4, evaluation_seconds=1.0)
    ledger.record("high", logical_calls=3, physical_calls=2, evaluation_seconds=2.0)
    snapshot = ledger.snapshot()
    assert snapshot["equivalent_high_calls"] == pytest.approx(2.8)
    assert snapshot["equivalent_high_calls_q1"] == pytest.approx(2.6)
    assert snapshot["equivalent_high_calls_q3"] == pytest.approx(3.2)
