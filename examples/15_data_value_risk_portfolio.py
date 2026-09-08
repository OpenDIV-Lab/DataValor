"""DataValue 拓展示例：风险折扣、反事实增量、组合协同和校准。"""

from __future__ import annotations

import json
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    product = DataProduct("sales-portfolio", "Sales portfolio", DataReference("memory://sales", "json"), "owner")
    request = ValuationRequest(product, (ValuationTarget("dataset", product.product_id, DataScope.DATASET),), ActorProfile("buyer-1", ActorRole.BUYER), TaskContext("forecast", "forecast demand"), costs=CostContext(preparation=80, adoption=40), options={"evaluation_vector": {"quality": 0.86}, "uncertainty": {"std_error": 0.06}})
    risk = RiskAdjustedValuator(base_value=2400, risk_aversion=0.35).value(request, RunContext("risk"))
    incremental = CounterfactualValuator(value_per_unit=2400).value(request.__class__(request.product, request.targets, request.buyer, request.task, request.rights, request.costs, options={"evaluation_vector": {"auc": 0.91}, "baseline_vector": {"auc": 0.82}}), RunContext("counterfactual"))
    portfolio = PortfolioValuator(risk_weight=0.2).value(request.__class__(request.product, request.targets, request.buyer, request.task, request.rights, request.costs, options={"portfolio_items": [{"target_id": "regional", "value": 1100, "uncertainty": 80, "group": "region"}, {"target_id": "channel", "value": 700, "uncertainty": 50, "group": "channel"}], "synergies": {"regional+channel": 260}}), RunContext("portfolio"))
    curve = build_value_curve([0, 1000, 2000, 3000], [0.0, 0.52, 0.76, 0.85], 2400)
    calibration = calibrate_values([800, 1200, 1800], [760, 1300, 1700])
    output = {"risk_adjusted": risk.estimates[0].__dict__, "counterfactual": incremental.estimates[0].__dict__, "portfolio": portfolio.estimates[0].__dict__, "value_curve": [point.__dict__ for point in curve], "calibration": calibration.__dict__}
    path = ROOT / "outputs/datavalue-extension/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "risk_value": risk.estimates[0].value, "portfolio_value": portfolio.estimates[0].value, "calibration_rmse": calibration.rmse}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

