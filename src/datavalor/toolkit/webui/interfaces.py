"""Optional, framework-neutral Web UI extension interfaces."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Mapping

from datavalor.core import ArtifactEnvelope, BaseComponent, RunContext

from .models import ApplicationSpec, ViewModel, ViewSpec


class ViewProvider(BaseComponent):
    """Transform artifacts into a framework-neutral view model."""

    @abstractmethod
    def build(
        self,
        view: ViewSpec,
        artifacts: Mapping[str, ArtifactEnvelope[Any]],
        context: RunContext,
    ) -> ViewModel:
        """Build a view model without starting a server."""


class WebApplicationFactory(BaseComponent):
    """Create a concrete optional Web UI application from declarative views."""

    @abstractmethod
    def create(
        self,
        application: ApplicationSpec,
        providers: tuple[ViewProvider, ...],
        context: RunContext,
    ) -> Any:
        """Return a framework-specific application object without running it."""

