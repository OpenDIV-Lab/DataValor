from decimal import Decimal

import pytest

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    ElasticityPricingModel,
    Money,
    PriceQuote,
    PricingObservation,
    QuoteRequest,
    RiskAdjustedPricingModel,
    SubscriptionPricingModel,
    TieredUsagePricingModel,
    audit_pricing_outcome,
    calibrate_quotes,
)


def _request(**context):
    product = DataProduct("p", "p", DataReference("memory://p", "json"), "owner")
    return QuoteRequest(product, market_context=context)


def test_tiered_usage_progressive_charge():
    quote = TieredUsagePricingModel(((100, "1"), (200, "0.5"))).quote(_request(usage=150), RunContext("r"))
    assert quote.price.amount == Decimal("125.00")
    assert quote.components["tier_0_charge"] == Decimal("100")
    assert quote.components["tier_1_charge"] == Decimal("25.0")


def test_subscription_and_risk_adjusted_quotes():
    subscription = SubscriptionPricingModel().quote(_request(period_fee=100, included_usage=10, usage=15, overage_unit_price=3, commitment_discount="0.1"), RunContext("r"))
    assert subscription.price.amount == Decimal("105.00")
    risk = RiskAdjustedPricingModel(risk_aversion=0.5).quote(_request(estimated_value=1000, std_error=100, buyer_share="0.5"), RunContext("r"))
    assert risk.price.amount < Decimal("500")
    assert risk.components["risk_penalty"] == Decimal("98.00")


def test_elasticity_model_updates_with_quantity_feedback():
    model = ElasticityPricingModel(initial_price=100, elasticity=1, learning_rate=0.1, target_quantity=10)
    request = _request()
    before = model.quote(request, RunContext("r")).price.amount
    model.observe(PricingObservation(model.quote(request, RunContext("r")), True, Decimal("20")), RunContext("r"))
    after = model.quote(request, RunContext("r")).price.amount
    assert before == Decimal("100.00") and after == Decimal("110.00")


def test_quote_calibration_and_outcome_audit():
    quotes = [PriceQuote("q1", "p", Money(Decimal("100")), "m"), PriceQuote("q2", "p", Money(Decimal("120")), "m")]
    calibration = calibrate_quotes(quotes, [Money(Decimal("90")), Money(Decimal("130"))], [True, False])
    assert calibration.mean_absolute_error == Decimal("10")
    assert calibration.acceptance_rate == Decimal("0.5")
    from datavalor.data_price import Allocation, Payment, PricingOutcome

    outcome = PricingOutcome("test", (Allocation("b", ("p",), Decimal("1")),), (Payment("b", "s", Money(Decimal("10")), "test", ("p",)),), seller_revenue={"s": Money(Decimal("10"))})
    assert audit_pricing_outcome(outcome)["status"] == "valid"
    assert audit_pricing_outcome(outcome)["revenue_reconciles"] is True


def test_tier_validation():
    with pytest.raises(ValueError):
        TieredUsagePricingModel(((100, 1), (100, 0.5)))

