"""Cross-cutting storage interfaces."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from .artifact import ArtifactEnvelope, ArtifactRef
from .component import BaseComponent
from .context import RunContext


class ArtifactStore(BaseComponent):
    """Persist and retrieve artifact envelopes independently of local paths."""

    @abstractmethod
    def put(self, artifact: ArtifactEnvelope[Any], context: RunContext) -> ArtifactRef:
        """Persist an artifact and return its stable reference."""

    @abstractmethod
    def get(self, reference: ArtifactRef, context: RunContext) -> ArtifactEnvelope[Any]:
        """Load an artifact after integrity and access checks."""

    @abstractmethod
    def exists(self, reference: ArtifactRef, context: RunContext) -> bool:
        """Check whether a referenced artifact is available."""

