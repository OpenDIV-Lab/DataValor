"""Pipeline contracts inspired by modular data-science workflow projects."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from .artifact import ArtifactEnvelope, ArtifactRef
from .component import BaseComponent
from .context import RunContext


@dataclass(frozen=True)
class PipelineNode:
    """Declarative invocation of a registered component."""

    node_id: str
    component: str
    inputs: Mapping[str, str] = field(default_factory=dict)
    outputs: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineSpec:
    """Versioned directed workflow; validation belongs to a runner implementation."""

    pipeline_id: str
    nodes: tuple[PipelineNode, ...]
    schema_version: str = "datavalor.pipeline/v1alpha1"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineResult:
    """Named output artifacts and execution diagnostics for a pipeline run."""

    pipeline_id: str
    outputs: Mapping[str, ArtifactRef]
    node_artifacts: Mapping[str, tuple[ArtifactRef, ...]] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class PipelineRunner(BaseComponent):
    """Execute a declarative pipeline without defining its storage backend."""

    @abstractmethod
    def run(
        self,
        pipeline: PipelineSpec,
        inputs: Mapping[str, ArtifactEnvelope[Any]],
        context: RunContext,
    ) -> PipelineResult:
        """Execute ``pipeline`` and return references to its outputs."""

