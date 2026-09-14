from decimal import Decimal

import pytest

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_price import (
    ONLINE_PRICING_MODELS,
    PRICING_MODELS,
    AcceptanceProbabilityModel,
    ExpectedRevenuePricingModel,
    Money,
    PriceQuote,
    PricingObservation,
    QuoteRequest,
    SafeExplorationPricingModel,
)
from datavalor.data_query import (
    QueryResult,
    QueryUtilityFeedback,
    UsageAggregator,
    UsageAnomalyDetector,
    UsageEvent,
)
from datavalor.data_value import (
    calibrate_values_by_group,
    evaluate_value_intervals,
    evaluate_value_ranking,
)
from datavalor.toolkit.analysis import ANALYZERS, AnalysisRequest, ValueRealizationAnalyzer


def _product():
    return DataProduct("p1", "Product", DataReference("memory://p1", "json"), "owner")


def _context():
    return RunContext("feedback", seed=7)


def test_usage_aggregation_utility_and_anomalies():
    events = (
        UsageEvent("e1", "p1", "b1", "query", 2, 10, 1.0, 0.1),
        UsageEvent("e1", "p1", "b1", "query", 2, 10, 1.0, 0.1),
        UsageEvent("e2", "p1", "b1", "query", 2, 20, 1.0, 0.8),
        UsageEvent("e3", "p1", "b1", "query", 20, 30, 1.0, 0.1),
    )
    aggregate = UsageAggregator().aggregate(events)[0]
    assert aggregate.event_count == 3
    assert aggregate.quantity == 24
    assert aggregate.diagnostics["duplicate_event_ids"] == ("e1",)

    utility = QueryUtilityFeedback().evaluate(
        QueryResult("r1", records=({"value": 1},)),
        events[0],
        task_id="forecast",
    )
    assert 0 <= utility.utility <= 1
    assert utility.diagnostics["event_id"] == "e1"

    codes = {
        item.code
        for item in UsageAnomalyDetector().detect(
            events,
            privacy_limits={"b1": 0.5},
            spike_factor=2,
        )
    }
    assert {"usage.duplicate_event", "usage.privacy_limit", "usage.volume_spike"} <= codes


def test_group_interval_and_ranking_calibration():
    rows = [
        {"buyer_id": "b1", "predicted": 10, "observed": 12},
        {"buyer_id": "b1", "predicted": 20, "observed": 24},
        {"buyer_id": "b2", "predicted": 10, "observed": 8},
    ]
    groups = calibrate_values_by_group(rows, ("buyer_id",), minimum_observations=2)
    assert len(groups) == 1
    assert groups[0].group == {"buyer_id": "b1"}

    intervals = evaluate_value_intervals(
        [
            {"lower": 8, "upper": 12, "observed": 10},
            {"lower": 18, "upper": 22, "observed": 25},
            {"lower": 4, "upper": 2, "observed": 3},
        ]
    )
    assert intervals.coverage_rate == pytest.approx(0.5)
    assert intervals.invalid == 1
    assert evaluate_value_ranking([1, 2, 3], [2, 1, 3]).pairwise_accuracy == pytest.approx(2 / 3)


def test_acceptance_expected_revenue_and_safe_exploration():
    probability = AcceptanceProbabilityModel()
    context = {"estimated_value": 100, "quality": 0.8}
    assert probability.predict(50, context) > probability.predict(150, context)

    observations = tuple(
        PricingObservation(
            PriceQuote(f"q{i}", "p1", Money(Decimal(price)), "historical"),
            accepted,
            context={**context},
        )
        for i, (price, accepted) in enumerate(((50, True), (60, True), (140, False), (160, False)))
    )
    assert probability.fit(observations, iterations=20).observations == 4

    request = QuoteRequest(
        _product(),
        ActorProfile("b1", ActorRole.BUYER),
        market_context={**context, "candidate_prices": (50, 100, 150)},
    )
    quote = ExpectedRevenuePricingModel(probability).quote(request, _context())
    assert quote.price.amount in {Decimal("50.00"), Decimal("100.00"), Decimal("150.00")}
    assert quote.components["expected_revenue"] >= 0

    online = SafeExplorationPricingModel((50, 60, 100), epsilon=0, max_change_ratio=0.2)
    first = online.quote(QuoteRequest(_product()), _context())
    online.observe(PricingObservation(first, True), _context())
    online.observe(PricingObservation(first, True), _context())
    second = online.quote(QuoteRequest(_product()), _context())
    assert online.trials[first.price.amount] == 1
    assert abs(second.price.amount - first.price.amount) <= first.price.amount * Decimal("0.2")


def test_joint_value_realization_analysis_and_registration():
    request = AnalysisRequest(
        (),
        ("estimated_value", "quoted_price", "realized_value"),
        group_by=("product_id",),
        options={
            "observations": (
                {"product_id": "p1", "estimated_value": 100, "quoted_price": 80, "accepted": True, "realized_value": 110},
                {"product_id": "p1", "estimated_value": 100, "quoted_price": 120, "accepted": False, "realized_value": 90},
                {"product_id": "p2", "estimated_value": 0, "quoted_price": 10, "accepted": True, "realized_value": 20},
            )
        },
    )
    result = ValueRealizationAnalyzer().analyze(request, _context())
    assert result.statistics["overall"]["acceptance_rate"] == pytest.approx(0.5)
    assert result.statistics["overall"]["quoted_revenue"] == 80
    assert result.diagnostics["invalid_indices"] == (2,)
    assert "value_realization" in ANALYZERS
    assert "pricing.expected_revenue" in PRICING_MODELS
    assert "pricing.safe_exploration" in ONLINE_PRICING_MODELS
