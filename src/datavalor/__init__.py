"""DataValor: a toolkit for data valorization."""

from ._catalog import MODULES, ModuleSpec, ValueStage
from .core import ArtifactEnvelope, ArtifactRef, ComponentSpec, Registry, RunContext

__all__ = [
    "MODULES",
    "ArtifactEnvelope",
    "ArtifactRef",
    "ComponentSpec",
    "ModuleSpec",
    "Registry",
    "RunContext",
    "ValueStage",
    "__version__",
]

__version__ = "0.1.0a0"
