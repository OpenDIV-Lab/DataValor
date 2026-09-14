"""Run usage feedback, value calibration, and feedback-driven pricing."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext, write_json
from datavalor.data_price import (
    AcceptanceProbabilityModel,
    ExpectedRevenuePricingModel,
    Money,
    PriceQuote,
    PricingObservation,
    QuoteRequest,
    SafeExplorationPricingModel,
)
from datavalor.data_query import UsageAggregator, UsageAnomalyDetector, UsageEvent
from datavalor.data_value import (
    calibrate_values_by_group,
    evaluate_value_intervals,
    evaluate_value_ranking,
)
from datavalor.toolkit.analysis import AnalysisRequest, ValueRealizationAnalyzer


def main() -> None:
    context = RunContext("stage12-feedback", seed=17)
    product = DataProduct(
        "retail-demand",
        "Retail demand",
        DataReference("memory://retail-demand", "json"),
        "seller-a",
    )
    events = (
        UsageEvent("u1", product.product_id, "buyer-a", "query", 10, 100, 1.2, 0.1),
        UsageEvent("u2", product.product_id, "buyer-a", "query", 12, 120, 1.1, 0.1),
        UsageEvent("u3", product.product_id, "buyer-a", "query", 40, 400, 2.5, 0.2),
    )
    value_rows = (
        {"buyer_id": "buyer-a", "task_id": "forecast", "predicted": 100, "observed": 112},
        {"buyer_id": "buyer-a", "task_id": "forecast", "predicted": 130, "observed": 125},
        {"buyer_id": "buyer-b", "task_id": "planning", "predicted": 90, "observed": 82},
        {"buyer_id": "buyer-b", "task_id": "planning", "predicted": 110, "observed": 101},
    )

    acceptance = AcceptanceProbabilityModel()
    history = tuple(
        PricingObservation(
            PriceQuote(f"history-{index}", product.product_id, Money(Decimal(price)), "observed"),
            accepted,
            context={"estimated_value": 120, "quality": 0.9, "rights_fit": 1.0},
        )
        for index, (price, accepted) in enumerate(((60, True), (80, True), (130, False), (150, False)))
    )
    training = acceptance.fit(history, iterations=100)
    quote_request = QuoteRequest(
        product,
        market_context={
            "estimated_value": 120,
            "quality": 0.9,
            "rights_fit": 1.0,
            "candidate_prices": (60, 80, 100, 120, 140),
        },
    )
    expected_quote = ExpectedRevenuePricingModel(acceptance).quote(quote_request, context)
    online = SafeExplorationPricingModel((60, 80, 100, 120), epsilon=0.1)
    online_quote = online.quote(QuoteRequest(product), context)
    online.observe(PricingObservation(online_quote, True), context)

    chain = ValueRealizationAnalyzer().analyze(
        AnalysisRequest(
            (),
            ("estimated_value", "quoted_price", "realized_value"),
            group_by=("buyer_id",),
            options={
                "observations": (
                    {"buyer_id": "buyer-a", "estimated_value": 120, "quoted_price": 80, "accepted": True, "realized_value": 125},
                    {"buyer_id": "buyer-b", "estimated_value": 100, "quoted_price": 120, "accepted": False, "realized_value": 82},
                )
            },
        ),
        context,
    )
    output = {
        "usage": [asdict(item) for item in UsageAggregator().aggregate(events)],
        "usage_anomalies": [asdict(item) for item in UsageAnomalyDetector().detect(events, spike_factor=2)],
        "group_calibration": [asdict(item) for item in calibrate_values_by_group(value_rows, ("buyer_id", "task_id"))],
        "interval_calibration": asdict(evaluate_value_intervals(({"lower": 90, "upper": 120, "observed": 112}, {"lower": 115, "upper": 135, "observed": 125}))),
        "ranking_calibration": asdict(evaluate_value_ranking((100, 130, 90, 110), (112, 125, 82, 101))),
        "acceptance_training": asdict(training),
        "expected_revenue_quote": asdict(expected_quote),
        "safe_exploration_quote": asdict(online_quote),
        "value_realization": asdict(chain),
    }
    target = Path("outputs/stage12-feedback-calibration/result.json")
    write_json(target, output)
    print(target)


if __name__ == "__main__":
    main()
