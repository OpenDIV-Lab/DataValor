from __future__ import annotations

from pathlib import Path

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


def _input(artifact_id, kind, payload):
    return ArtifactEnvelope(artifact_id, kind, "datavalor.input/v1alpha1", ComponentSpec("test", "1", "test", "input"), payload)


def test_stage1_config_runs_and_persists_lineage(tmp_path: Path):
    from dataclasses import replace

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

    records = (
        {"id": "1", "email": "a@example.test", "region": "east", "score": 1},
        {"id": "1", "email": None, "region": "east", "score": "bad"},
        {"id": "1", "email": "a@example.test", "region": "east", "score": 1},
    )
    product = DataProduct("workflow-product", "Workflow product", DataReference("memory://rows", "iterable"), "owner", rights=RightsBundle(purposes=("quality_assessment",)))
    config = load_workflow_config(Path(__file__).parents[1] / "configs/workflows/stage1_quality.json")

    def run_with_records(ctx):
        return replace(ctx.run, config={**ctx.run.config, "records": records})

    def governance(inputs, ctx):
        run = run_with_records(ctx)
        metadata = LocalMetadataExtractor().inspect(inputs["product"], run)
        return {"metadata": metadata, "policy": RightsPolicyEvaluator().evaluate(inputs["product"], "quality_assessment", metadata, run), "security": SensitiveFieldScanner().scan(inputs["product"], {}, run)}

    def profile(inputs, ctx):
        return BasicDataProfiler().profile(inputs["product"], ProfileRequest(options={"records": records}), ctx.run)

    def evaluation(inputs, ctx):
        return CompositeEvaluator().evaluate(inputs["product"], EvaluationRequest(options={"records": records, "required_fields": ("id", "email", "region", "score"), "field_types": {"score": "number"}}), (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()), ctx.run)

    result = UnifiedWorkflowRunner(LocalArtifactStore(tmp_path), {"stage1.governance": governance, "stage1.profile": profile, "stage1.evaluation": evaluation}).run(config, {"product": _input("p", "data_product", product), "records": _input("r", "data_records", records)}, RunContext("run-1"))
    assert result.status.value == "succeeded"
    assert [stage.stage_id for stage in result.stages] == ["governance", "profile", "evaluation"]
    evaluation_ref = result.outputs["evaluation"]
    envelope = LocalArtifactStore(tmp_path).get(evaluation_ref, RunContext("run-1"))
    assert {parent.artifact_id for parent in envelope.parents} >= {"p", "r"}
    assert envelope.payload["metrics"][1]["statistics"]["duplicate_count"] == 1
