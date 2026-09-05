"""阶段 3：符号估值、学习型估值、贡献度和价值分摊的完整链路。

运行：``PYTHONPATH=src python examples/08_stage3_advanced_valuation.py``
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
    GroupShapleyValuator,
    LearnedLinearValuator,
    QualityAdjustedValuator,
    ScenarioValuator,
    SymbolicValuator,
    TabularTaskUtility,
    ValuationRequest,
    ValuationTarget,
    allocate_value_by_contribution,
    bootstrap_loo_values,
    pairwise_interactions,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/examples/stage2_valuation_records.jsonl"


def _input(artifact_id: str, kind: str, payload: Any) -> ArtifactEnvelope[Any]:
    return ArtifactEnvelope(artifact_id, kind, "datavalor.input/v1alpha1", ComponentSpec("example.input", "1.0.0", "example", "input"), payload)


def main() -> None:
    rows = tuple(json.loads(line) for line in DATA_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    product = DataProduct("stage3-mobility-v1", "城市出行训练样本（合成）", DataReference(str(DATA_PATH), "jsonl", record_count=len(rows)), "city-data-owner", rights=RightsBundle(purposes=("valuation", "quality_assessment"), commercial_use=False), tags=("mobility", "valuation", "synthetic"))
    task = TaskContext("demand-forecast", "训练下一周需求预测模型", utility_metric="tabular_task_utility")
    buyer = ActorProfile("logistics-buyer", ActorRole.BUYER, budget=Decimal("1200"), preferences={"value_multiplier": 1.15})
    model = LearnedLinearValuator(("quality", "uniqueness", "buyer_multiplier"))
    config = load_workflow_config(ROOT / "configs/workflows/stage3_advanced_valuation.json")
    context = RunContext("stage3-workflow-001", seed=31, actor_id=buyer.actor_id, task_id=task.task_id, config={"workflow": config.workflow_id})
    store = LocalArtifactStore(ROOT / "outputs/stage3-valuation")

    def gov(inputs, stage):
        run = replace(stage.run, config={**stage.run.config, "records": inputs["records"]})
        metadata = LocalMetadataExtractor().inspect(inputs["product"], run)
        return {"metadata": metadata, "policy": RightsPolicyEvaluator().evaluate(inputs["product"], "valuation", metadata, run), "security": SensitiveFieldScanner().scan(inputs["product"], {}, run)}

    def profile(inputs, stage):
        return BasicDataProfiler().profile(inputs["product"], ProfileRequest(options={"records": inputs["records"]}), stage.run)

    def evaluation(inputs, stage):
        return CompositeEvaluator().evaluate(inputs["product"], EvaluationRequest(options={"records": inputs["records"], "required_fields": ("id", "segment", "label", "fresh"), "field_types": {"label": "integer", "fresh": "number"}}), (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()), stage.run)

    def vector(inputs):
        values = {item.dimension: float(item.value or 0.0) for item in inputs["evaluation"].metrics}
        return {"quality": values.get("completeness", 0.0), "uniqueness": 1.0 - values.get("uniqueness", 0.0)}

    def symbolic(inputs, stage):
        request = ValuationRequest(inputs["product"], (ValuationTarget("dataset", inputs["product"].product_id, DataScope.DATASET),), inputs["buyer"], inputs["task"], inputs["product"].rights, CostContext(adoption=Decimal("35")), evaluation_artifacts=(stage.input_refs["evaluation"], stage.input_refs["governance"]), options={"evaluation_vector": vector(inputs)})
        return SymbolicValuator(stage.parameters["expression"], base_value=float(stage.parameters["base_value"]), currency=stage.parameters["currency"]).value(request, stage.run)

    def quality_adjusted(inputs, stage):
        request = ValuationRequest(inputs["product"], (ValuationTarget("dataset", inputs["product"].product_id, DataScope.DATASET),), inputs["buyer"], inputs["task"], inputs["product"].rights, CostContext(adoption=Decimal("35")), evaluation_artifacts=(stage.input_refs["evaluation"], stage.input_refs["governance"]), options={"evaluation_vector": vector(inputs)})
        return QualityAdjustedValuator(float(stage.parameters["base_value"]), stage.parameters["currency"], quality_floor=float(stage.parameters.get("quality_floor", 0.5))).value(request, stage.run)

    def scenarios(inputs, stage):
        values = vector(inputs)
        scenarios = {"conservative": {"quality": values.get("quality", 0.0) * 0.8, "uniqueness": values.get("uniqueness", 0.0) * 0.9}, "base": values, "optimistic": {"quality": min(1.0, values.get("quality", 0.0) * 1.1), "uniqueness": min(1.0, values.get("uniqueness", 0.0) * 1.05)}}
        request = ValuationRequest(inputs["product"], (ValuationTarget("dataset", inputs["product"].product_id, DataScope.DATASET),), inputs["buyer"], inputs["task"], inputs["product"].rights, options={"evaluation_vector": values})
        return ScenarioValuator(scenarios, base_value=float(stage.parameters["base_value"]), currency=stage.parameters["currency"]).value(request, stage.run)

    def training(inputs, stage):
        requests = []
        for quality, uniqueness in ((0.4, 0.5), (0.7, 0.8), (0.9, 0.95), (0.2, 0.3)):
            requests.append(ValuationRequest(inputs["product"], (ValuationTarget("dataset", inputs["product"].product_id, DataScope.DATASET),), inputs["buyer"], inputs["task"], inputs["product"].rights, options={"evaluation_vector": {"quality": quality, "uniqueness": uniqueness}}))
        observed = [420.0, 760.0, 1010.0, 280.0]
        return model.fit(requests, observed, stage.run)

    def learned(inputs, stage):
        request = ValuationRequest(inputs["product"], (ValuationTarget("dataset", inputs["product"].product_id, DataScope.DATASET),), inputs["buyer"], inputs["task"], inputs["product"].rights, options={"evaluation_vector": vector(inputs)})
        return model.value(request, stage.run)

    def contribution(inputs, stage):
        records = {str(row["id"]): row for row in inputs["records"]}
        utility = TabularTaskUtility(records)
        units = tuple(ValuationTarget(item, inputs["product"].product_id, DataScope.SAMPLE) for item in records)
        request = ContributionRequest(inputs["product"], units, inputs["task"], {"max_records": int(stage.parameters.get("max_records", 10))})
        return ExactShapleyValuator().value_contributions(request, utility, stage.run)

    def group_contribution(inputs, stage):
        records = {str(row["id"]): row for row in inputs["records"]}
        groups = {}
        for key, row in records.items():
            groups.setdefault(str(row.get("segment", "unknown")), []).append(key)
        utility = TabularTaskUtility(records)
        units = tuple(ValuationTarget(name, inputs["product"].product_id, DataScope.GROUP, tuple(members)) for name, members in groups.items())
        request = ContributionRequest(inputs["product"], units, inputs["task"], {"groups": groups, "max_groups": int(stage.parameters.get("max_groups", 8))})
        return GroupShapleyValuator().value_contributions(request, utility, stage.run)

    def interactions(inputs, stage):
        records = {str(row["id"]): row for row in inputs["records"]}
        utility = TabularTaskUtility(records)
        def scorer(selection, ctx):
            return utility.score(inputs["product"], selection, inputs["task"], ctx)
        return {"interactions": pairwise_interactions(tuple(records), scorer, context=stage.run)}

    def bootstrap(inputs, stage):
        records = {str(row["id"]): row for row in inputs["records"]}
        utility = TabularTaskUtility(records)
        def scorer(selection, ctx):
            return utility.score(inputs["product"], selection, inputs["task"], ctx)
        return bootstrap_loo_values(tuple(records), scorer, samples=int(stage.parameters.get("samples", 128)), seed=int(stage.parameters.get("seed", stage.run.seed)), context=stage.run)

    def allocation(inputs, stage):
        total = inputs["valuation"].estimates[0].value
        return {"total_value": total, "allocations": allocate_value_by_contribution(total, inputs["contribution"].contributions, negative_policy=stage.parameters.get("negative_policy", "zero")), "source_method": inputs["valuation"].method}

    handlers = {"stage3.governance": gov, "stage3.profile": profile, "stage3.evaluation": evaluation, "stage3.quality_adjusted": quality_adjusted, "stage3.symbolic_valuation": symbolic, "stage3.scenarios": scenarios, "stage3.model_training": training, "stage3.learned_valuation": learned, "stage3.contribution": contribution, "stage3.group_contribution": group_contribution, "stage3.interactions": interactions, "stage3.bootstrap": bootstrap, "stage3.allocation": allocation}
    inputs = {"product": _input("stage3-input-product", "data_product", product), "records": _input("stage3-input-records", "data_records", rows), "task": _input("stage3-input-task", "task_context", task), "buyer": _input("stage3-input-buyer", "actor_profile", buyer)}
    result = UnifiedWorkflowRunner(store, handlers).run(config, inputs, context)
    summary = {"workflow_id": result.workflow_id, "run_id": result.run_id, "status": result.status.value, "stages": [{"stage_id": item.stage_id, "status": item.status.value, "artifact_id": item.artifact.artifact_id if item.artifact else None, "artifact_uri": item.artifact.uri if item.artifact else None} for item in result.stages], "diagnostics": dict(result.diagnostics)}
    output = ROOT / "outputs/stage3-valuation/summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.status.value == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
