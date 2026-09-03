"""DataValor: a toolkit for data valorization."""

from ._catalog import MODULES, ModuleSpec, ValueStage
from .core import (
    ArtifactEnvelope,
    ArtifactRef,
    ComponentSpec,
    Registry,
    RunContext,
    UnifiedWorkflowRunner,
    WorkflowRunResult,
    WorkflowSpec,
    WorkflowStage,
    load_workflow_config,
)

__all__ = [
    "MODULES",
    "ArtifactEnvelope",
    "ArtifactRef",
    "ComponentSpec",
    "ModuleSpec",
    "Registry",
    "RunContext",
    "UnifiedWorkflowRunner",
    "WorkflowRunResult",
    "WorkflowSpec",
    "WorkflowStage",
    "load_workflow_config",
    "ValueStage",
    "__version__",
]

__version__ = "0.1.0a0"
