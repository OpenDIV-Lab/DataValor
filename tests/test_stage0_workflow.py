from __future__ import annotations

from pathlib import Path

import pytest

from datavalor.core import (
    ArtifactEnvelope,
    ArtifactStatus,
    ComponentSpec,
    LocalArtifactStore,
    RunContext,
    UnifiedWorkflowRunner,
    WorkflowSpec,
    load_workflow_config,
)
from datavalor.data_query import UsageEvent


def _input(name: str, payload):
    return ArtifactEnvelope(
        name,
        "input",
        "datavalor.input/v1alpha1",
        ComponentSpec("test.input", "1", "tests", "input"),
        payload,
    )


def test_stage0_workflow_persists_lineage_and_round_trips(tmp_path: Path):
    workflow = WorkflowSpec.from_mapping(
        {
            "workflow_id": "test.chain",
            "stages": [
                {"stage_id": "profile", "handler": "test.profile", "artifact_kind": "profile", "inputs": {"records": "records"}},
                {"stage_id": "value", "handler": "test.value", "artifact_kind": "valuation", "inputs": {"profile": "profile"}},
            ],
        }
    )
    runner = UnifiedWorkflowRunner(
        LocalArtifactStore(tmp_path),
        {"test.profile": lambda inputs, context: {"count": len(inputs["records"])}, "test.value": lambda inputs, context: {"value": inputs["profile"]["count"] * 10}},
    )
    result = runner.run(workflow, {"records": _input("records", (1, 2, 3))}, RunContext("run-1", seed=9))

    assert result.status is ArtifactStatus.SUCCEEDED
    assert tuple(result.outputs) == ("profile", "value")
    value_ref = result.outputs["value"]
    stored = LocalArtifactStore(tmp_path).get(value_ref, RunContext("read"))
    assert stored.payload == {"value": 30}
    assert [parent.artifact_id for parent in stored.parents] == ["test.chain/run-1/profile"]
    profile = LocalArtifactStore(tmp_path).get(result.outputs["profile"], RunContext("read"))
    assert [parent.artifact_id for parent in profile.parents] == ["records"]
    assert stored.created_at.tzinfo is not None


def test_stage0_workflow_reports_failed_stage_and_stops(tmp_path: Path):
    workflow = WorkflowSpec.from_mapping(
        {
            "workflow_id": "test.failure",
            "stages": [
                {"stage_id": "ok", "handler": "test.ok", "artifact_kind": "profile", "inputs": {"records": "records"}},
                {"stage_id": "broken", "handler": "test.broken", "artifact_kind": "valuation", "inputs": {"profile": "ok"}},
                {"stage_id": "never", "handler": "test.never", "artifact_kind": "analysis", "inputs": {"value": "broken"}},
            ],
        }
    )
    runner = UnifiedWorkflowRunner(LocalArtifactStore(tmp_path), {"test.ok": lambda inputs, context: {"ok": True}, "test.broken": lambda inputs, context: (_ for _ in ()).throw(RuntimeError("boom")), "test.never": lambda inputs, context: None})
    result = runner.run(workflow, {"records": _input("records", ())}, RunContext("run-2"))

    assert result.status is ArtifactStatus.FAILED
    assert result.diagnostics["failed_stage"] == "broken"
    assert [item.stage_id for item in result.stages] == ["ok", "broken"]
    failure = LocalArtifactStore(tmp_path).get(result.stages[-1].artifact, RunContext("read"))
    assert failure.status is ArtifactStatus.FAILED
    assert failure.payload["error_type"] == "RuntimeError"
    assert "boom" in failure.payload["message"]


def test_stage0_rejects_nested_envelopes_and_bad_config(tmp_path: Path):
    with pytest.raises(ValueError, match="future stage"):
        WorkflowSpec.from_mapping(
            {
                "workflow_id": "bad",
                "stages": [
                    {"stage_id": "first", "handler": "x", "artifact_kind": "x", "inputs": {"x": "second"}},
                    {"stage_id": "second", "handler": "x", "artifact_kind": "x"},
                ],
            }
        )
    workflow = WorkflowSpec.from_mapping({"workflow_id": "nested", "stages": [{"stage_id": "one", "handler": "x", "artifact_kind": "x", "inputs": {"input": "input"}}]})
    nested = ArtifactEnvelope("nested-output", "x", "v1", ComponentSpec("test", "1", "tests", "x"), "payload")
    runner = UnifiedWorkflowRunner(LocalArtifactStore(tmp_path), {"x": lambda inputs, context: nested})
    result = runner.run(workflow, {"input": _input("input", 1)}, RunContext("run-3"))
    assert result.status is ArtifactStatus.FAILED
    assert result.diagnostics["error_type"] == "TypeError"


def test_stage0_json_config_is_loadable():
    spec = load_workflow_config("configs/workflows/stage0_unified.json")
    assert spec.workflow_id == "stage0.unified_value_chain"
    assert spec.initial_inputs == ("product", "records")
    assert len(spec.metadata["config_sha256"]) == 64
    assert [stage.stage_id for stage in spec.stages] == ["governance", "profile", "evaluation", "valuation", "pricing", "market", "query", "usage", "analysis"]


def test_usage_event_is_separate_from_payment():
    event = UsageEvent("usage-1", "product-1", "buyer-1", "query", records_returned=12, compute_seconds=0.8)
    assert event.operation == "query"
    assert event.records_returned == 12
    assert not hasattr(event, "amount")


def test_local_store_detects_tampered_artifact(tmp_path: Path):
    store = LocalArtifactStore(tmp_path)
    reference = store.put(_input("checksum", {"value": 1}), RunContext("write"))
    reference_path = Path(reference.uri)
    reference_path.write_text(reference_path.read_text(encoding="utf-8").replace('"value": 1', '"value": 2'), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.get(reference, RunContext("read"))
