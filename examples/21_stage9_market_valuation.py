"""Run market-oriented valuation methods on explicit phase-one evidence."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from datavalor.core import (
    CostContext,
    DataProduct,
    DataReference,
    DataScope,
    RunContext,
    write_json,
)
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


def request(product, **options):
    return ValuationRequest(
        product,
        (ValuationTarget("dataset", product.product_id, DataScope.DATASET),),
        costs=CostContext(preparation=60, adoption=40),
        options=options,
    )


def main() -> None:
    product = DataProduct(
        "demand-signals",
        "Demand signals",
        DataReference("memory://signals", "json"),
        "supplier",
    )
    context = RunContext("stage9-example", seed=17)

    market = MarketContextValuator(base_value=3000).value(
        request(
            product,
            market_factors={
                "demand_fit": 0.86,
                "quality": 0.90,
                "freshness": 0.82,
                "scarcity": 0.65,
                "rights": 0.80,
                "supply_stability": 0.92,
            },
            scarcity_weight=0.35,
            risk_penalty=90,
        ),
        context,
    )
    scarcity = ScarcityAdjustedValuator(1800, 0.4).value(
        request(product, scarcity=0.65, task_relevance=0.86), context
    )
    incremental = IncrementalCoverageValuator(2500).value(
        request(
            product,
            coverage_dimensions={"entity": 0.55, "time": 0.80, "region": 0.35},
            coverage_weights={"entity": 2, "time": 2, "region": 1},
            quality=0.90,
            task_relevance=0.86,
        ),
        context,
    )
    substitution = SubstitutionAdjustedValuator(2400).value(
        request(
            product,
            substitutes=(
                {"coverage": 0.55, "quality_ratio": 0.80, "available": True},
                {"coverage": 0.30, "quality_ratio": 0.95, "available": True},
            ),
            unique_fraction=0.48,
        ),
        context,
    )
    time_value = TimeDecayValuator(2200, half_life_days=45).value(
        request(product, age_days=12, time_sensitivity=0.8), context
    )
    stream = UpdateStreamValuator().value(
        request(
            product,
            updates=(
                {"period": 0, "marginal_value": 900},
                {"period": 1, "marginal_value": 600, "delivery_probability": 0.95},
                {"period": 2, "marginal_value": 420, "delivery_probability": 0.90},
            ),
            discount_rate=0.08,
        ),
        context,
    )
    reports = (market, scarcity, incremental, substitution, time_value, stream)
    consensus = ValuationEnsemble().combine(reports, "dataset")
    sensitivity = ValuationSensitivityAnalyzer().analyze(
        MarketContextValuator(3000),
        request(product, market_factors={"demand_fit": 0.86, "quality": 0.90}),
        context,
        {"demand_fit": (0.60, 0.80, 1.00), "quality": (0.70, 0.85, 1.00)},
    )
    selection = BudgetConstrainedPortfolioSelector().select(
        (
            {"item_id": "signals", "cost": 950, "value": market.estimates[0].value, "group": "core"},
            {"item_id": "regional", "cost": 500, "value": 820, "group": "coverage"},
            {"item_id": "history", "cost": 350, "value": 430, "group": "coverage"},
        ),
        1500,
        required_groups=("core", "coverage"),
    )
    output = {
        "valuations": {report.method: asdict(report) for report in reports},
        "consensus": asdict(consensus),
        "sensitivity": [asdict(item) for item in sensitivity],
        "budget_selection": asdict(selection),
    }
    target = Path("outputs/stage9-market-valuation/result.json")
    write_json(target, output)
    print(target)


if __name__ == "__main__":
    main()
