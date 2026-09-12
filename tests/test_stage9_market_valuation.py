from dataclasses import replace

import pytest

from datavalor.core import CostContext, DataProduct, DataReference, DataScope, RunContext
from datavalor.data_value import (
    BudgetConstrainedPortfolioSelector,
    IncrementalCoverageValuator,
    MarketContextValuator,
    ScarcityAdjustedValuator,
    SubstitutionAdjustedValuator,
    TimeDecayValuator,
    UpdateStreamValuator,
    ValuationEnsemble,
    ValuationRequest,
    ValuationSensitivityAnalyzer,
    ValuationTarget,
)


def _request(**options):
    product = DataProduct("market-data", "Market data", DataReference("memory://market", "json"), "owner")
    target = (ValuationTarget("dataset", product.product_id, DataScope.DATASET),)
    return ValuationRequest(product, target, costs=CostContext(adoption=20), options=options)


def test_market_context_exposes_each_factor_and_cost():
    request = _request(market_factors={"demand_fit": 0.8, "quality": 0.9, "freshness": 0.75, "scarcity": 0.6, "rights": 0.8, "supply_stability": 0.95}, scarcity_weight=0.5, risk_penalty=10)
    estimate = MarketContextValuator(2000).value(request, RunContext("market")).estimates[0]
    assert 0 < estimate.value < 2000
    assert estimate.components["scarcity_multiplier"] == pytest.approx(1.24)
    assert estimate.components["total_cost"] == 20
    assert estimate.components["risk_penalty"] == 10


def test_scarcity_premium_is_gated_by_task_relevance():
    valuator = ScarcityAdjustedValuator(1000, scarcity_weight=1)
    low = valuator.value(_request(scarcity=1, task_relevance=0), RunContext("low")).estimates[0]
    high = valuator.value(_request(scarcity=1, task_relevance=1), RunContext("high")).estimates[0]
    assert low.value == 0
    assert high.value == 1980


def test_incremental_coverage_uses_dimensions_weights_and_quality():
    request = _request(coverage_dimensions={"entity": 0.5, "time": 1.0}, coverage_weights={"entity": 1, "time": 3}, quality=0.8)
    estimate = IncrementalCoverageValuator(1000).value(request, RunContext("coverage")).estimates[0]
    assert estimate.components["incremental_coverage"] == pytest.approx(0.875)
    assert estimate.value == pytest.approx(680)


def test_substitution_discount_respects_unique_fraction():
    request = _request(substitutes=({"coverage": 0.8, "quality_ratio": 0.9},), unique_fraction=0.4)
    estimate = SubstitutionAdjustedValuator(1000).value(request, RunContext("substitute")).estimates[0]
    assert estimate.components["best_substitute_score"] == pytest.approx(0.72)
    assert estimate.components["retention_factor"] == 0.4
    assert estimate.value == 380


def test_time_decay_half_life_and_zero_time_sensitivity():
    valuator = TimeDecayValuator(1000, half_life_days=30)
    decayed = valuator.value(_request(age_days=30), RunContext("time")).estimates[0]
    insensitive = valuator.value(_request(age_days=300, time_sensitivity=0), RunContext("time")).estimates[0]
    assert decayed.components["decay_factor"] == pytest.approx(0.5)
    assert decayed.value == 480
    assert insensitive.value == 980
    with pytest.raises(ValueError):
        valuator.value(_request(age_days=1, half_life_days=0), RunContext("bad"))


def test_update_stream_discount_delivery_quality_and_cost():
    request = _request(updates=({"period": 0, "marginal_value": 100}, {"period": 1, "marginal_value": 110, "delivery_probability": 0.5, "quality": 0.8}), discount_rate=0.1)
    estimate = UpdateStreamValuator().value(request, RunContext("stream")).estimates[0]
    assert estimate.components["present_value"] == pytest.approx(140)
    assert estimate.value == pytest.approx(120)


def test_ensemble_and_sensitivity_do_not_change_report_contract():
    request = _request(market_factors={"quality": 0.8})
    market = MarketContextValuator(1000)
    first = market.value(request, RunContext("one"))
    second = IncrementalCoverageValuator(1000).value(replace(request, options={"incremental_coverage": 0.5}), RunContext("two"))
    consensus = ValuationEnsemble().combine((first, second), "dataset")
    assert consensus.lower <= consensus.value <= consensus.upper
    observations = ValuationSensitivityAnalyzer().analyze(market, request, RunContext("sensitivity"), {"quality": (0.5, 1.0)})
    assert len(observations) == 2
    assert observations[0].estimated_value < observations[1].estimated_value


def test_budget_selector_exact_constraints_and_exclusions():
    items = (
        {"item_id": "a", "cost": 60, "value": 100, "group": "region"},
        {"item_id": "b", "cost": 40, "value": 80, "group": "time"},
        {"item_id": "c", "cost": 30, "value": 45, "group": "region"},
        {"item_id": "blocked", "cost": 1, "value": 999, "eligible": False},
    )
    result = BudgetConstrainedPortfolioSelector().select(items, 100, required_groups=("region", "time"))
    assert result.selected_ids == ("a", "b")
    assert result.total_value == 180
    assert result.diagnostics["feasible"]
    assert result.excluded["blocked"] == "ineligible"


def test_validation_boundaries():
    with pytest.raises(ValueError):
        MarketContextValuator(-1)
    with pytest.raises(ValueError):
        TimeDecayValuator(half_life_days=0)
    with pytest.raises(ValueError):
        ValuationEnsemble().combine((), "missing")
    with pytest.raises(ValueError):
        BudgetConstrainedPortfolioSelector().select((), -1)
