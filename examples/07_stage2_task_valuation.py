"""阶段 2：把阶段 1 质量证据用于任务相关估值和数据单元贡献分析。

运行：``PYTHONPATH=src python examples/07_stage2_task_valuation.py``
"""

from __future__ import annotations

import json
from dataclasses import replace
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
from datavalor.data_eval import (
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    EvaluationRequest,
    FieldValidityMetric,
)
from datavalor.data_gov import LocalMetadataExtractor, RightsPolicyEvaluator, SensitiveFieldScanner
from datavalor.data_prof import BasicDataProfiler, ProfileRequest
from datavalor.data_value import (
    ContributionRequest,
    ExactShapleyValuator,
    MonteCarloShapleyValuator,
    TabularTaskUtility,
    ValuationRequest,
    ValuationTarget,
    WeightedUserTaskValuator,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/examples/stage2_valuation_records.jsonl"


def _input(artifact_id: str, kind: str, payload: Any) -> ArtifactEnvelope[Any]:
    return ArtifactEnvelope(artifact_id, kind, "datavalor.input/v1alpha1", ComponentSpec("example.input", "1.0.0", "example", "input"), payload)


def _governance(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    run = RunContext(ctx.run.run_id, seed=ctx.run.seed, actor_id=ctx.run.actor_id, config={**ctx.run.config, "records": records})
    metadata = LocalMetadataExtractor().inspect(product, run)
    policy = RightsPolicyEvaluator().evaluate(product, str(ctx.parameters.get("operation", "valuation")), metadata, run)
    security = SensitiveFieldScanner().scan(product, {}, run)
    return {"metadata": metadata, "policy": policy, "security": security}


def _profile(inputs, ctx):
    return BasicDataProfiler().profile(inputs["product"], ProfileRequest(options={"records": inputs["records"]}), ctx.run)


def _evaluation(inputs, ctx):
    report = CompositeEvaluator().evaluate(inputs["product"], EvaluationRequest(options={"records": inputs["records"], "required_fields": ("id", "segment", "label", "fresh"), "field_types": {"label": "integer", "fresh": "number"}}), (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()), ctx.run)
    return report


def _valuation(inputs, ctx):
    task, buyer, product = inputs["task"], inputs["buyer"], inputs["product"]
    metrics = {item.dimension: float(item.value or 0.0) for item in inputs["evaluation"].metrics}
    request = ValuationRequest(product, (ValuationTarget("dataset", product.product_id, DataScope.DATASET),), buyer, task, product.rights, CostContext(adoption=Decimal("35")), evaluation_artifacts=tuple(ctx.input_refs[name] for name in ("evaluation", "governance")), options={"evaluation_vector": {"quality": metrics.get("completeness", 0.0), "uniqueness": 1.0 - metrics.get("uniqueness", 0.0)}})
    result = WeightedUserTaskValuator(float(ctx.parameters.get("base_value", 1000)), str(ctx.parameters.get("currency", "CNY"))).value(request, ctx.run)
    return result


def _contribution(inputs, ctx):
    records = {str(row["id"]): row for row in inputs["records"]}
    utility = TabularTaskUtility(records)
    units = tuple(ValuationTarget(item, inputs["product"].product_id, DataScope.SAMPLE) for item in records)
    request = ContributionRequest(inputs["product"], units, inputs["task"], {"samples": int(ctx.parameters.get("samples", 512)), "seed": int(ctx.parameters.get("seed", ctx.run.seed))})
    valuator = MonteCarloShapleyValuator() if ctx.parameters.get("method") == "shapley_monte_carlo" else ExactShapleyValuator()
    report = valuator.value_contributions(request, utility, ctx.run)
    return replace(report, diagnostics={**report.diagnostics, "profile_artifact": ctx.input_refs["profile"].artifact_id, "evaluation_artifact": ctx.input_refs["evaluation"].artifact_id})


def main() -> None:
    rows = tuple(json.loads(line) for line in DATA_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    product = DataProduct("stage2-mobility-v1", "城市出行训练样本（合成）", DataReference(str(DATA_PATH), "jsonl", record_count=len(rows)), "city-data-owner", rights=RightsBundle(purposes=("valuation", "quality_assessment"), commercial_use=False), tags=("mobility", "valuation", "synthetic"))
    task = TaskContext("demand-forecast", "训练下一周需求预测模型", utility_metric="tabular_task_utility", metadata={"metric_weights": {"quality": 0.7, "uniqueness": 0.3}})
    buyer = ActorProfile("logistics-buyer", ActorRole.BUYER, budget=Decimal("1200"), preferences={"value_multiplier": 1.15})
    config = load_workflow_config(ROOT / "configs/workflows/stage2_valuation.json")
    context = RunContext("stage2-workflow-001", seed=23, actor_id=buyer.actor_id, task_id=task.task_id, config={"workflow": config.workflow_id})
    store = LocalArtifactStore(ROOT / "outputs/stage2-valuation")
    inputs = {"product": _input("stage2-input-product", "data_product", product), "records": _input("stage2-input-records", "data_records", rows), "task": _input("stage2-input-task", "task_context", task), "buyer": _input("stage2-input-buyer", "actor_profile", buyer)}
    result = UnifiedWorkflowRunner(store, {"stage2.governance": _governance, "stage2.profile": _profile, "stage2.evaluation": _evaluation, "stage2.valuation": _valuation, "stage2.contribution": _contribution}).run(config, inputs, context)
    summary = {"workflow_id": result.workflow_id, "run_id": result.run_id, "status": result.status.value, "stages": [{"stage_id": item.stage_id, "status": item.status.value, "artifact_id": item.artifact.artifact_id if item.artifact else None, "artifact_uri": item.artifact.uri if item.artifact else None} for item in result.stages], "diagnostics": dict(result.diagnostics)}
    output = ROOT / "outputs/stage2-valuation/summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.status.value == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
