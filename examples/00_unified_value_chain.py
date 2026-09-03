"""阶段 0：用一份配置跑通 DataValor 的统一主链路。

链路：DataProduct → Governance → Profile → Evaluation → Valuation →
Pricing → Market → Query → UsageEvent → Analysis。

运行：PYTHONPATH=src python examples/00_unified_value_chain.py
结果会写入 ``outputs/stage0-unified``，同时在终端打印摘要。
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from datavalor.core import (
    ActorProfile,
    ActorRole,
    ArtifactEnvelope,
    ComponentSpec,
    CostContext,
    DataProduct,
    DataReference,
    DataScope,
    LocalArtifactStore,
    RightsBundle,
    RunContext,
    TaskContext,
    UnifiedWorkflowRunner,
    load_workflow_config,
)
from datavalor.data_eval import EvaluationReport, EvaluationRequest, LexicalDiversityMetric
from datavalor.data_gov import GovernanceDecision, GovernanceReport
from datavalor.data_market import TransactionRecord
from datavalor.data_price import Ask, Bid, Money, PricingRequest, SecondPriceAuction
from datavalor.data_prof import DatasetProfile, FieldProfile
from datavalor.data_query import (
    ExternalQueryExecutor,
    GovernedDataAgent,
    QueryRequest,
    QueryResultGuard,
    RightsQueryAuthorizer,
    UsageEvent,
    VannaQueryPlanner,
)
from datavalor.data_value import ValuationRequest, ValuationTarget, WeightedUserTaskValuator
from datavalor.toolkit.analysis import AnalysisResult

ROOT = Path(__file__).resolve().parents[1]
RECORDS = tuple(json.loads(line) for line in (ROOT / "data/examples/stage0_records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())


def _input(artifact_id: str, kind: str, payload: Any) -> ArtifactEnvelope[Any]:
    return ArtifactEnvelope(artifact_id, kind, "datavalor.input/v1alpha1", ComponentSpec("example.input", "1.0.0", "example", "input"), payload)


def _governance(inputs, ctx):
    product: DataProduct = inputs["product"]
    decision = GovernanceDecision.ALLOW if "query" in product.rights.purposes and "valuation" in product.rights.purposes else GovernanceDecision.REVIEW
    return GovernanceReport(product.product_id, decision, policies=(ctx.parameters.get("operation", "operation"), "rights"), diagnostics={"run_id": ctx.run.run_id, "purposes": product.rights.purposes})


def _profile(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    fields = []
    for name in sorted({key for row in records for key in row}):
        values = [row.get(name) for row in records]
        present = [value for value in values if value is not None]
        inferred = "number" if present and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present) else "string"
        fields.append(FieldProfile(name, inferred, len(values), len(values) - len(present), len({str(value) for value in present})))
    return DatasetProfile(product.product_id, len(records), len(fields), tuple(fields), properties={"source": product.data.uri}, diagnostics={"run_id": ctx.run.run_id})


def _evaluation(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    metric = LexicalDiversityMetric(str(ctx.parameters.get("text_field", "text")))
    result = metric.compute(product, EvaluationRequest(scope=DataScope.DATASET, options={"records": records}), ctx.run)
    return EvaluationReport(product.product_id, (result,), diagnostics={"run_id": ctx.run.run_id, "profile_used": inputs["profile"].product_id})


def _valuation(inputs, ctx):
    product, evaluation = inputs["product"], inputs["evaluation"]
    task = TaskContext("traffic-forecast", "预测下一时段交通需求", utility_metric="lexical_diversity", metadata={"metric_weights": {"quality": 1.0}})
    buyer = ActorProfile("logistics-buyer", ActorRole.BUYER, budget=Decimal("800"), preferences={"value_multiplier": 1.1})
    vector = {metric.dimension: float(metric.value or 0.0) for metric in evaluation.metrics}
    request = ValuationRequest(product, (ValuationTarget("product", product.product_id, DataScope.PRODUCT),), buyer, task, product.rights, CostContext(adoption=Decimal(str(ctx.parameters.get("adoption_cost", "0")))), options={"evaluation_vector": {"quality": vector.get("diversity", 0.0)}})
    return WeightedUserTaskValuator(float(ctx.parameters.get("base_value", 1000)), str(ctx.parameters.get("currency", "CNY"))).value(request, ctx.run)


def _pricing(inputs, ctx):
    product, valuation = inputs["product"], inputs["valuation"]
    value = Decimal(str(valuation.estimates[0].value))
    bids = (Bid("buyer-main", "logistics-buyer", (product.product_id,), Money(value)), Bid("buyer-alt", "alternative-buyer", (product.product_id,), Money(Decimal("420"))))
    asks = (Ask("seller-reserve", product.owner_id, (product.product_id,), Money(Decimal("250"))),)
    return SecondPriceAuction().price(PricingRequest((product,), bids=bids, asks=asks), ctx.run)


def _market(inputs, ctx):
    product, pricing = inputs["product"], inputs["pricing"]
    status = "settled" if pricing.allocations and pricing.payments else "not_traded"
    return TransactionRecord(f"tx-{ctx.run.run_id}", pricing, status, rights={product.product_id: product.rights}, diagnostics={"run_id": ctx.run.run_id})


def _query(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    buyer = ActorProfile("logistics-buyer", ActorRole.BUYER)
    planner = VannaQueryPlanner(generator=lambda question, **_: {"sql": "SELECT id, email, region, label FROM stage0_records"})
    executor = ExternalQueryExecutor(executor=lambda statements, **_: {"records": records, "answer": f"returned {len(records)} records"}, backend="memory")
    agent = GovernedDataAgent(RightsQueryAuthorizer(purpose="query"), planner, executor, QueryResultGuard(redact_fields=tuple(ctx.parameters.get("redact_fields", ())), max_rows=int(ctx.parameters.get("max_rows", 100))))
    return agent.run(QueryRequest("query-stage0", buyer, "查询训练数据", (product,), max_rows=int(ctx.parameters.get("max_rows", 100))), ctx.run)


def _usage(inputs, ctx):
    product, query = inputs["product"], inputs["query"]
    return UsageEvent(f"usage-{ctx.run.run_id}", product.product_id, "logistics-buyer", "query", quantity=1.0, records_returned=len(query.records), compute_seconds=0.02, metadata={"truncated": query.truncated})


def _analysis(inputs, ctx):
    pricing = inputs["pricing"]
    return AnalysisResult("stage0.analysis", {"run_id": ctx.run.run_id, "stages": tuple(inputs), "transaction_status": inputs["market"].status, "query_rows": len(inputs["query"].records), "usage_quantity": inputs["usage"].quantity, "price_semantics": {"valuation_unit": inputs["valuation"].estimates[0].unit, "payment_amount": str(pricing.payments[0].amount.amount) if pricing.payments else None}})


def main() -> None:
    product = DataProduct("stage0-traffic-v1", "交通需求训练数据（合成）", DataReference("data/examples/stage0_records.jsonl", "jsonl", record_count=len(RECORDS)), "city-data-owner", rights=RightsBundle(purposes=("valuation", "query"), commercial_use=False))
    config = load_workflow_config(ROOT / "configs/workflows/stage0_unified.json")
    context = RunContext("stage0-demo-001", seed=42, actor_id="logistics-buyer", config={"workflow": config.workflow_id})
    store = LocalArtifactStore(ROOT / "outputs/stage0-unified")
    inputs = {"product": _input("input-product", "data_product", product), "records": _input("input-records", "data_records", RECORDS)}
    handlers = {"example.governance": _governance, "example.profile": _profile, "example.evaluation": _evaluation, "example.valuation": _valuation, "example.pricing": _pricing, "example.market": _market, "example.query": _query, "example.usage": _usage, "example.analysis": _analysis}
    result = UnifiedWorkflowRunner(store, handlers).run(config, inputs, context)
    summary = {"workflow_id": result.workflow_id, "run_id": result.run_id, "status": result.status.value, "stages": [{"stage_id": item.stage_id, "status": item.status.value, "artifact_id": item.artifact.artifact_id if item.artifact else None} for item in result.stages], "diagnostics": dict(result.diagnostics)}
    (ROOT / "outputs/stage0-unified/summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.status.value == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
