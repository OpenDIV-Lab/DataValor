"""阶段 1：用统一 artifact 链路执行 DataGov → DataProf → DataEval。

运行：``PYTHONPATH=src python examples/06_stage1_unified_workflow.py``

脚本使用阶段 0 相同的 ``UnifiedWorkflowRunner`` 和 ``LocalArtifactStore``。
每个阶段都会产生带 checksum、父引用和运行诊断的 JSON artifact，便于将
质量准入结果交给后续 DataValue/DataPrice，而不把质量分数直接当成价格。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from datavalor.core import (
    ArtifactEnvelope,
    ComponentSpec,
    DataProduct,
    DataReference,
    LocalArtifactStore,
    RightsBundle,
    RunContext,
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
from datavalor.data_gov import (
    LocalMetadataExtractor,
    RightsPolicyEvaluator,
    SensitiveFieldScanner,
)
from datavalor.data_prof import BasicDataProfiler, ProfileRequest

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/examples/stage1_quality_records.jsonl"


def _input(artifact_id: str, kind: str, payload: Any) -> ArtifactEnvelope[Any]:
    return ArtifactEnvelope(
        artifact_id,
        kind,
        "datavalor.input/v1alpha1",
        ComponentSpec("example.input", "1.0.0", "example", "input"),
        payload,
    )


def _run_with_records(ctx, records):
    return replace(ctx.run, config={**ctx.run.config, "records": records})


def _governance(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    run = _run_with_records(ctx, records)
    metadata = LocalMetadataExtractor().inspect(product, run)
    operation = str(ctx.parameters.get("operation", "quality_assessment"))
    policy = RightsPolicyEvaluator().evaluate(product, operation, metadata, run)
    security = SensitiveFieldScanner().scan(product, {"operation": operation}, run)
    # A mapping keeps all three independently auditable outputs in one stage
    # artifact while preserving their domain models for downstream consumers.
    return {"metadata": metadata, "policy": policy, "security": security}


def _profile(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    request = ProfileRequest(
        sample_size=ctx.parameters.get("sample_size"),
        options={"records": records},
    )
    return BasicDataProfiler().profile(product, request, ctx.run)


def _evaluation(inputs, ctx):
    product, records = inputs["product"], inputs["records"]
    options = {
        "records": records,
        "required_fields": tuple(ctx.parameters.get("required_fields", ())),
        "field_types": dict(ctx.parameters.get("field_types", {})),
    }
    report = CompositeEvaluator().evaluate(
        product,
        EvaluationRequest(options=options),
        (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()),
        ctx.run,
    )
    # Preserve the upstream stage IDs in diagnostics; the runner also records
    # artifact parents, so both semantic and physical lineage are available.
    return replace(
        report,
        diagnostics={
            **report.diagnostics,
            "governance_decision": inputs["governance"]["policy"].decision.value,
            "profile_record_count": inputs["profile"].record_count,
        },
    )


def main() -> None:
    rows = tuple(
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    product = DataProduct(
        "stage1-customer-quality-v1",
        "客户分群质量检查样本（合成）",
        DataReference(str(DATA_PATH), "jsonl", record_count=len(rows)),
        "data-owner",
        rights=RightsBundle(purposes=("quality_assessment",), commercial_use=False),
        tags=("customer", "quality", "synthetic"),
        metadata={"license_id": "CC-BY-4.0-DEMO"},
    )
    config = load_workflow_config(ROOT / "configs/workflows/stage1_quality.json")
    context = RunContext("stage1-workflow-001", seed=17, actor_id="quality-reviewer", config={"workflow": config.workflow_id})
    store = LocalArtifactStore(ROOT / "outputs/stage1-workflow")
    inputs = {
        "product": _input("stage1-input-product", "data_product", product),
        "records": _input("stage1-input-records", "data_records", rows),
    }
    handlers = {
        "stage1.governance": _governance,
        "stage1.profile": _profile,
        "stage1.evaluation": _evaluation,
    }
    result = UnifiedWorkflowRunner(store, handlers).run(config, inputs, context)
    summary = {
        "workflow_id": result.workflow_id,
        "run_id": result.run_id,
        "status": result.status.value,
        "stages": [
            {
                "stage_id": item.stage_id,
                "status": item.status.value,
                "artifact_id": item.artifact.artifact_id if item.artifact else None,
                "artifact_uri": item.artifact.uri if item.artifact else None,
            }
            for item in result.stages
        ],
        "diagnostics": dict(result.diagnostics),
    }
    output = ROOT / "outputs/stage1-workflow/summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if result.status.value == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
