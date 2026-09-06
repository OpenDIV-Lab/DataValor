"""阶段 5：重复市场仿真、策略 benchmark 与统计/前沿分析。

运行：``PYTHONPATH=src python examples/10_stage5_market_benchmark_analysis.py``
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from datavalor.core import ActorProfile, ActorRole, DataProduct, DataReference, RunContext
from datavalor.data_market import Listing, ListingStatus, MarketSnapshot
from datavalor.data_market.simulation import (
    BudgetPacingStrategy,
    FiniteMarketSimulator,
    FixedReserveSellerStrategy,
    FixedShadingStrategy,
    TruthfulStrategy,
)
from datavalor.data_price import FirstPriceAuction
from datavalor.toolkit.analysis import (
    AnalysisRequest,
    BootstrapAnalyzer,
    ComparisonRequest,
    PairedComparator,
    ParetoFrontierAnalyzer,
)
from datavalor.toolkit.benchmark import (
    BenchmarkCase,
    BenchmarkSpec,
    MatrixBenchmarkRunner,
    SimulationReportMetric,
)

ROOT = Path(__file__).resolve().parents[1]


def make_simulation(strategy_name):
    product = DataProduct(
        "stage5-mobility-v1",
        "城市出行数据",
        DataReference("memory://stage5", "jsonl", record_count=10000),
        "seller",
        tags=("mobility",),
    )
    buyer = ActorProfile(
        "buyer",
        ActorRole.BUYER,
        budget=Decimal("800"),
        currency="CNY",
        preferences={"value": Decimal("500"), "product_id": product.product_id},
    )
    seller = ActorProfile(
        "seller",
        ActorRole.SUPPLIER,
        preferences={"product_id": product.product_id},
    )
    snapshot = MarketSnapshot(
        (Listing("stage5-listing", product, "seller", ListingStatus.ACTIVE),),
        (buyer, seller),
    )
    strategies = {
        "truthful": TruthfulStrategy(),
        "fixed_shading": FixedShadingStrategy(0.85),
        "budget_pacing": BudgetPacingStrategy(1.0, rounds=12, aggressiveness=1.0),
    }
    strategy = strategies[strategy_name]
    seller_strategy = FixedReserveSellerStrategy(300, quantity=1)
    context = RunContext(
        f"stage5-{strategy_name}",
        metadata={
            "products": (product,),
            "strategy_actors": ("buyer", "seller"),
            "market_context": {"supply": {product.product_id: Decimal("1")}},
        },
    )
    return FiniteMarketSimulator(FirstPriceAuction()).run(
        snapshot, (strategy, seller_strategy), 12, context
    )


def main():
    components = {
        name: (lambda case, context, selected=name: {"report": make_simulation(selected)})
        for name in ("truthful", "fixed_shading", "budget_pacing")
    }
    case = BenchmarkCase(
        "mobility-12-rounds",
        {},
        parameters={"description": "同一 seller reserve 下比较三种买方策略"},
        tags=("market", "stage5"),
    )
    benchmark = BenchmarkSpec(
        "stage5-strategy-benchmark",
        tuple(components),
        (case,),
        ("simulation",),
        repetitions=5,
        seed=2025,
    )
    report = MatrixBenchmarkRunner(components, {"simulation": SimulationReportMetric()}).run(
        benchmark, RunContext("stage5-benchmark")
    )
    observations = [
        {"component": item.component, **item.measurements} for item in report.observations
    ]
    by_component = {}
    for component in components:
        values = [
            item.measurements["total_revenue"]
            for item in report.observations
            if item.component == component
        ]
        by_component[component] = values
    bootstrap = BootstrapAnalyzer().analyze(
        AnalysisRequest((), ("total_revenue", "conversion_rate"), options={
            "total_revenue": by_component["truthful"],
            "conversion_rate": [
                item.measurements["conversion_rate"]
                for item in report.observations
                if item.component == "truthful"
            ],
            "samples": 1000,
        }),
        RunContext("stage5-analysis", seed=77),
    )
    comparison = PairedComparator().compare(
        ComparisonRequest(
            "truthful",
            ("fixed_shading", "budget_pacing"),
            (),
            ("total_revenue",),
            {
                "truthful": by_component["truthful"],
                "fixed_shading": by_component["fixed_shading"],
                "budget_pacing": by_component["budget_pacing"],
            },
        ),
        RunContext("stage5-comparison", seed=78),
    )
    rows = [
        {
            "strategy": component,
            "revenue": report.aggregates[component]["total_revenue"]["mean"],
            "conversion": report.aggregates[component]["conversion_rate"]["mean"],
            "volatility": report.aggregates[component]["revenue_std"]["mean"],
        }
        for component in components
    ]
    frontier = ParetoFrontierAnalyzer().frontier(
        AnalysisRequest(
            (),
            ("revenue", "volatility"),
            options={
                "rows": rows,
                "directions": {"volatility": "min"},
                "weights": {"revenue": 1.0, "volatility": -0.2},
            },
        ),
        RunContext("stage5-frontier"),
    )
    output = {
        "benchmark": report,
        "raw_observations": observations,
        "bootstrap": bootstrap,
        "paired_comparison": comparison,
        "frontier": frontier,
    }
    out_dir = ROOT / "outputs/stage5-market"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "status": "succeeded",
        "output": str(out_dir / "result.json"),
        "observation_count": report.diagnostics["observation_count"],
        "aggregates": report.aggregates,
        "frontier": frontier.statistics["frontier"],
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
