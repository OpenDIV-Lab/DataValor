"""A small, deterministic runner for the unified DataValor value chain.

The existing module interfaces deliberately remain independent.  This module
only supplies the stage-0 glue: a declarative ordered chain, common envelope
creation, parent lineage, configuration loading, and failure diagnostics.
It does not know how governance, valuation, pricing, or querying is
implemented; callers provide named handlers for those stages.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from .artifact import ArtifactEnvelope, ArtifactRef, ArtifactStatus
from .component import ComponentSpec
from .context import RunContext
from .interfaces import ArtifactStore
from .io import file_sha256


class StageHandler(Protocol):
    """Callable used by one workflow stage.

    ``inputs`` contains payloads resolved from the stage's ``inputs`` mapping;
    ``context`` contains the run, stage parameters, and parent references.
    Returning an :class:`ArtifactEnvelope` is intentionally rejected: stages
    return domain payloads and the runner owns the one canonical envelope.
    """

    def __call__(self, inputs: Mapping[str, Any], context: "StageContext") -> Any: ...


@dataclass(frozen=True)
class WorkflowStage:
    """One ordered stage in a unified chain."""

    stage_id: str
    handler: str
    artifact_kind: str
    inputs: Mapping[str, str] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "datavalor.stage/v1alpha1"
    required: bool = True


@dataclass(frozen=True)
class WorkflowSpec:
    """Versioned, linear workflow specification.

    ``inputs`` maps a handler-local name to either an initial input key or a
    previous ``stage_id``.  A stage may only refer to an earlier stage, which
    makes the execution order and lineage unambiguous.
    """

    workflow_id: str
    stages: tuple[WorkflowStage, ...]
    schema_version: str = "datavalor.workflow/v1alpha1"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    initial_inputs: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "WorkflowSpec":
        if not isinstance(payload, Mapping):
            raise ValueError("workflow configuration must be an object")
        workflow_id = str(payload.get("workflow_id", "")).strip()
        if not workflow_id:
            raise ValueError("workflow configuration requires workflow_id")
        raw_stages = payload.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise ValueError("workflow configuration requires a non-empty stages list")
        initial_inputs = payload.get("initial_inputs", ())
        if not isinstance(initial_inputs, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in initial_inputs):
            raise ValueError("workflow initial_inputs must be a list of non-empty names")
        if len(set(initial_inputs)) != len(initial_inputs):
            raise ValueError("workflow initial_inputs must not contain duplicates")
        stages: list[WorkflowStage] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_stages):
            if not isinstance(raw, Mapping):
                raise ValueError(f"workflow stage {index} must be an object")
            stage_id = str(raw.get("stage_id", "")).strip()
            handler = str(raw.get("handler", "")).strip()
            artifact_kind = str(raw.get("artifact_kind", "")).strip()
            if not stage_id or not handler or not artifact_kind:
                raise ValueError(f"workflow stage {index} requires stage_id, handler, and artifact_kind")
            schema_version = str(raw.get("schema_version", "datavalor.stage/v1alpha1")).strip()
            if not schema_version:
                raise ValueError(f"workflow stage {stage_id} schema_version must not be empty")
            if stage_id in seen:
                raise ValueError(f"duplicate workflow stage_id: {stage_id}")
            seen.add(stage_id)
            inputs = raw.get("inputs", {})
            parameters = raw.get("parameters", {})
            if not isinstance(inputs, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in inputs.items()):
                raise ValueError(f"workflow stage {stage_id} inputs must map names to source keys")
            if not isinstance(parameters, Mapping):
                raise ValueError(f"workflow stage {stage_id} parameters must be an object")
            stages.append(
                WorkflowStage(
                    stage_id=stage_id,
                    handler=handler,
                    artifact_kind=artifact_kind,
                    inputs=dict(inputs),
                    parameters=dict(parameters),
                    schema_version=schema_version,
                    required=bool(raw.get("required", True)),
                )
            )
        known = set()
        for stage in stages:
            for source in stage.inputs.values():
                if source not in known and source not in {"product", "records", "request", "config"}:
                    # Other initial input names are valid; only a source that
                    # looks like a future stage is an ordering error.  The
                    # runner performs the definitive check against initial
                    # inputs, while this catches accidental forward refs.
                    if source in {item.stage_id for item in stages}:
                        raise ValueError(f"stage {stage.stage_id} references a future stage: {source}")
            known.add(stage.stage_id)
        return cls(
            workflow_id,
            tuple(stages),
            str(payload.get("schema_version", "datavalor.workflow/v1alpha1")),
            dict(payload.get("metadata", {})) if isinstance(payload.get("metadata", {}), Mapping) else {},
            tuple(initial_inputs),
        )


def load_workflow_config(path: str | Path) -> WorkflowSpec:
    """Load JSON, or YAML when PyYAML is explicitly installed."""

    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8")) if target.suffix.lower() == ".json" else _load_yaml(target)
    spec = WorkflowSpec.from_mapping(payload)
    return replace(spec, metadata={**spec.metadata, "config_path": str(target), "config_sha256": file_sha256(target)})


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("YAML workflow configuration requires PyYAML") from exc
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("workflow configuration must be an object")
    return payload


@dataclass(frozen=True)
class StageContext:
    """Context visible to one handler without exposing runner internals."""

    run: RunContext
    stage: WorkflowStage
    input_refs: Mapping[str, ArtifactRef]

    @property
    def parameters(self) -> Mapping[str, Any]:
        return self.stage.parameters


@dataclass(frozen=True)
class StageExecution:
    """Status and artifact reference for one attempted stage."""

    stage_id: str
    status: ArtifactStatus
    artifact: ArtifactRef | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRunResult:
    """Complete run trace, including the failed stage when a run stops."""

    workflow_id: str
    run_id: str
    status: ArtifactStatus
    outputs: Mapping[str, ArtifactRef]
    stages: tuple[StageExecution, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class UnifiedWorkflowRunner:
    """Execute a configured chain and persist every stage envelope.

    The default behavior is fail-fast.  A stage marked ``required: false``
    records a failed artifact and continues, making optional enrichment
    stages explicit without hiding their failure.
    """

    def __init__(self, store: ArtifactStore, handlers: Mapping[str, StageHandler]):
        self.store = store
        self.handlers = dict(handlers)

    def run(
        self,
        workflow: WorkflowSpec,
        inputs: Mapping[str, ArtifactEnvelope[Any]],
        context: RunContext,
    ) -> WorkflowRunResult:
        self._validate_inputs(workflow, inputs)
        available: dict[str, tuple[Any, ArtifactRef]] = {
            key: (envelope.payload, self._input_ref(envelope)) for key, envelope in inputs.items()
        }
        outputs: dict[str, ArtifactRef] = {}
        executions: list[StageExecution] = []
        for stage in workflow.stages:
            handler = self.handlers.get(stage.handler)
            if handler is None:
                result = self._record_failure(
                    workflow,
                    stage,
                    context,
                    (item[1] for item in available.values()),
                    "HandlerNotFound",
                    f"unknown handler: {stage.handler}",
                )
                executions.append(result)
                if stage.required:
                    return self._failed(workflow, context, outputs, executions, result)
                continue
            try:
                values: dict[str, Any] = {}
                refs: dict[str, ArtifactRef] = {}
                for local_name, source in stage.inputs.items():
                    if source not in available:
                        raise KeyError(f"stage {stage.stage_id} input {local_name!r} references unavailable source {source!r}")
                    values[local_name], refs[local_name] = available[source]
                payload = handler(values, StageContext(context, stage, refs))
                if isinstance(payload, ArtifactEnvelope):
                    raise TypeError("stage handlers must return a domain payload, not ArtifactEnvelope")
                parents = self._unique_refs(refs.values())
                envelope = ArtifactEnvelope(
                    artifact_id=f"{workflow.workflow_id}/{context.run_id}/{stage.stage_id}",
                    kind=stage.artifact_kind,
                    schema_version=stage.schema_version,
                    producer=ComponentSpec(stage.handler, "1.0.0", "workflow", "stage"),
                    payload=payload,
                    parents=parents,
                    diagnostics={
                        "run_id": context.run_id,
                        "seed": context.seed,
                        "workflow_id": workflow.workflow_id,
                        "stage_id": stage.stage_id,
                        "handler": stage.handler,
                        "parameters": dict(stage.parameters),
                        "input_sources": dict(stage.inputs),
                        "workflow_metadata": dict(workflow.metadata),
                    },
                )
                reference = self.store.put(envelope, context)
                available[stage.stage_id] = (payload, reference)
                outputs[stage.stage_id] = reference
                executions.append(StageExecution(stage.stage_id, ArtifactStatus.SUCCEEDED, reference, {"parent_count": len(parents)}))
            except Exception as exc:  # stage failures are part of the public run result
                refs = tuple(item[1] for item in available.values())
                result = self._record_failure(workflow, stage, context, refs, type(exc).__name__, str(exc))
                executions.append(result)
                if stage.required:
                    return self._failed(workflow, context, outputs, executions, result)
        status = ArtifactStatus.SUCCEEDED if all(item.status is ArtifactStatus.SUCCEEDED for item in executions) else ArtifactStatus.PARTIAL
        return WorkflowRunResult(workflow.workflow_id, context.run_id, status, dict(outputs), tuple(executions), {"completed_stages": tuple(item.stage_id for item in executions if item.status is ArtifactStatus.SUCCEEDED)})

    @staticmethod
    def _input_ref(envelope: ArtifactEnvelope[Any]) -> ArtifactRef:
        return ArtifactRef(envelope.artifact_id, envelope.kind, envelope.schema_version)

    @staticmethod
    def _unique_refs(refs: Any) -> tuple[ArtifactRef, ...]:
        result: list[ArtifactRef] = []
        seen: set[str] = set()
        for ref in refs:
            if ref.artifact_id not in seen:
                seen.add(ref.artifact_id)
                result.append(ref)
        return tuple(result)

    @staticmethod
    def _validate_inputs(workflow: WorkflowSpec, inputs: Mapping[str, ArtifactEnvelope[Any]]) -> None:
        if not inputs:
            raise ValueError("workflow requires at least one initial input artifact")
        missing_initial = [name for name in workflow.initial_inputs if name not in inputs]
        if missing_initial:
            raise KeyError(f"workflow is missing initial input artifacts: {tuple(missing_initial)}")
        for stage in workflow.stages:
            for local_name, source in stage.inputs.items():
                if source not in inputs and source not in {item.stage_id for item in workflow.stages}:
                    raise KeyError(f"stage {stage.stage_id} input {local_name!r} references unavailable source {source!r}")

    def _record_failure(
        self,
        workflow: WorkflowSpec,
        stage: WorkflowStage,
        context: RunContext,
        parents: Any,
        error_type: str,
        message: str,
    ) -> StageExecution:

        payload = {"stage_id": stage.stage_id, "handler": stage.handler, "error_type": error_type, "message": message}
        envelope = ArtifactEnvelope(
            artifact_id=f"{workflow.workflow_id}/{context.run_id}/{stage.stage_id}/failure",
            kind="workflow.failure",
            schema_version="datavalor.workflow.failure/v1alpha1",
            producer=ComponentSpec("workflow.runner", "1.0.0", "core", "workflow_runner"),
            payload=payload,
            status=ArtifactStatus.FAILED,
            parents=self._unique_refs(parents),
            diagnostics={
                "run_id": context.run_id,
                "seed": context.seed,
                "workflow_id": workflow.workflow_id,
                "stage_id": stage.stage_id,
                "parameters": dict(stage.parameters),
                "input_sources": dict(stage.inputs),
                "workflow_metadata": dict(workflow.metadata),
                "traceback": traceback.format_exc(limit=8),
            },
        )
        reference = self.store.put(envelope, context)
        return StageExecution(stage.stage_id, ArtifactStatus.FAILED, reference, payload)

    @staticmethod
    def _failed(workflow: WorkflowSpec, context: RunContext, outputs: Mapping[str, ArtifactRef], executions: list[StageExecution], failed: StageExecution) -> WorkflowRunResult:
        return WorkflowRunResult(workflow.workflow_id, context.run_id, ArtifactStatus.FAILED, dict(outputs), tuple(executions), {"failed_stage": failed.stage_id, "error_type": failed.diagnostics.get("error_type"), "completed_stages": tuple(item.stage_id for item in executions if item.status is ArtifactStatus.SUCCEEDED)})


__all__ = [
    "StageContext",
    "StageExecution",
    "StageHandler",
    "UnifiedWorkflowRunner",
    "WorkflowRunResult",
    "WorkflowSpec",
    "WorkflowStage",
    "load_workflow_config",
]
