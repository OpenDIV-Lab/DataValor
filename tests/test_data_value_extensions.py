import pytest

from datavalor.core import (
    ActorProfile,
    ActorRole,
    CostContext,
    DataProduct,
    DataReference,
    DataScope,
    RunContext,
    TaskContext,
)
from datavalor.data_value import (
    CounterfactualValuator,
    PortfolioValuator,
    RiskAdjustedValuator,
    ValuationRequest,
    ValuationTarget,
    build_value_curve,
    calibrate_values,
)


def _request(**options):
    product = DataProduct("p", "p", DataReference("memory://p", "json"), "owner")
    target = (ValuationTarget("dataset", "p", DataScope.DATASET),)
    return ValuationRequest(product, target, ActorProfile("buyer", ActorRole.BUYER), TaskContext("task", "forecast"), costs=CostContext(adoption=10), options=options)


def test_risk_adjusted_valuator_converts_uncertainty_to_monetary_discount():
    report = RiskAdjustedValuator(base_value=1000, risk_aversion=0.5).value(_request(evaluation_vector={"quality": 0.8}, uncertainty={"std_error": 0.1}), RunContext("r"))
    estimate = report.estimates[0]
    assert estimate.value < 790
    assert estimate.uncertainty["monetary_std_error"] == 100
    assert estimate.uncertainty["lower_95"] < estimate.uncertainty["upper_95"]


def test_counterfactual_and_portfolio_value():
    counter = CounterfactualValuator(value_per_unit=100).value(_request(evaluation_vector={"auc": 0.85}, baseline_vector={"auc": 0.75}), RunContext("r"))
    assert counter.estimates[0].value == 0
    portfolio = PortfolioValuator(risk_weight=0.1).value(_request(portfolio_items=[{"target_id": "a", "value": 100, "uncertainty": 10}, {"target_id": "b", "value": 50, "uncertainty": 5}], synergies={"a+b": 20}), RunContext("r"))
    assert portfolio.estimates[0].value > 160
    assert portfolio.estimates[0].components["synergy_value"] == 20


def test_calibration_and_monotone_value_curve():
    calibration = calibrate_values([100, 120, 150], [110, 115, 160])
    assert calibration.observations == 3
    assert calibration.mae > 0
    curve = build_value_curve([0, 10, 20], [0.0, 0.7, 0.6], 1000)
    assert [point.utility for point in curve] == pytest.approx([0.0, 0.65, 0.65])
    assert curve[-1].cumulative_value == pytest.approx(1000)
