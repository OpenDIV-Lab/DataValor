"""任务相关估值：加权效用、LOO、精确 Shapley 和 Monte Carlo Shapley。

运行：PYTHONPATH=src python examples/01_task_value_and_shapley.py
"""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal

from datavalor.core import (
    ActorProfile,
    ActorRole,
    CostContext,
    DataProduct,
    DataReference,
    DataScope,
    RightsBundle,
    RunContext,
    TaskContext,
)
from datavalor.data_value import (
    ValuationRequest,
    ValuationTarget,
    WeightedUserTaskValuator,
    exact_shapley_values,
    leave_one_out_values,
    monte_carlo_shapley_values,
)

RECORDS = {
    "r01": {"segment": "urban", "label": 1, "fresh": 0.98},
    "r02": {"segment": "urban", "label": 0, "fresh": 0.95},
    "r03": {"segment": "rural", "label": 1, "fresh": 0.83},
    "r04": {"segment": "rural", "label": 0, "fresh": 0.80},
    "r05": {"segment": "urban", "label": 1, "fresh": 0.72},
}


def utility(selection: tuple[str, ...], _context: RunContext | None = None) -> float:
    """一个可解释的下游分类效用：覆盖、标签平衡和新鲜度共同决定分数。"""
    rows = [RECORDS[row_id] for row_id in selection]
    if not rows:
        return 0.0
    coverage = min(1.0, len(rows) / 4.0)
    segments = {row["segment"] for row in rows}
    diversity = len(segments) / 2.0
    positives = sum(row["label"] for row in rows) / len(rows)
    balance = 1.0 - abs(positives - 0.5) * 2.0
    freshness = sum(row["fresh"] for row in rows) / len(rows)
    return round(0.55 * coverage + 0.20 * diversity + 0.15 * balance + 0.10 * freshness, 6)


def main() -> None:
    product = DataProduct(
        product_id="mobility-demo-v1",
        title="城市出行训练样本（合成）",
        data=DataReference("memory://mobility-demo", "records", record_count=len(RECORDS), schema_ref="demo.schema.json"),
        owner_id="city-lab",
        rights=RightsBundle(purposes=("model_training", "valuation"), commercial_use=False),
        tags=("mobility", "classification"),
    )
    task = TaskContext(
        "demand-forecasting",
        "训练下一周需求预测模型",
        utility_metric="composite_utility",
        metadata={"metric_weights": {"quality": 0.7, "coverage": 0.3}},
    )
    buyer = ActorProfile("retail-ml", ActorRole.BUYER, budget=Decimal("1200"), preferences={"value_multiplier": 1.15})
    context = RunContext("example-01", seed=7, actor_id=buyer.actor_id, task_id=task.task_id)

    request = ValuationRequest(
        product=product,
        targets=(ValuationTarget("dataset", product.product_id, DataScope.DATASET, tuple(RECORDS)),),
        buyer=buyer,
        task=task,
        rights=product.rights,
        costs=CostContext(adoption=Decimal("35")),
        options={"evaluation_vector": {"quality": 0.86, "coverage": 0.75}},
    )
    weighted = WeightedUserTaskValuator(base_value=1000, currency="CNY").value(request, context)
    ids = tuple(RECORDS)
    reports = {
        "weighted_user_task": [asdict(item) for item in weighted.estimates],
        "leave_one_out": [asdict(item) for item in leave_one_out_values(ids, utility, context=context).contributions],
        "shapley_exact": [asdict(item) for item in exact_shapley_values(ids, utility, context=context).contributions],
        "shapley_monte_carlo": [asdict(item) for item in monte_carlo_shapley_values(ids, utility, samples=512, seed=7, context=context).contributions],
    }
    print(json.dumps({"product_id": product.product_id, "task_id": task.task_id, "utility_full": utility(ids), "reports": reports}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
