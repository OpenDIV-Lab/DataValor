"""Extension interfaces for benchmark data, perturbations, metrics, and runners."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Mapping

from datavalor.core import ArtifactEnvelope, BaseComponent, RunContext

from .models import BenchmarkCase, BenchmarkReport, BenchmarkSpec


class BenchmarkDataProvider(BaseComponent):
    """Materialize real, synthetic, or cached benchmark inputs."""

    @abstractmethod
    def load(self, case: BenchmarkCase, context: RunContext) -> Mapping[str, ArtifactEnvelope[Any]]:
        """Load all named inputs while recording their provenance."""


class DataPerturbation(BaseComponent):
    """Apply a deterministic shift, corruption, split, or resampling operation."""

    @abstractmethod
    def apply(
        self,
        artifact: ArtifactEnvelope[Any],
        parameters: Mapping[str, Any],
        context: RunContext,
    ) -> ArtifactEnvelope[Any]:
        """Return a new artifact whose parent is the unmodified input."""


class BenchmarkMetric(BaseComponent):
    """Measure one property of a component's benchmark outputs."""

    @abstractmethod
    def measure(
        self,
        case: BenchmarkCase,
        outputs: Mapping[str, ArtifactEnvelope[Any]],
        context: RunContext,
    ) -> Mapping[str, float | int | bool | None]:
        """Return named measurements without performing leaderboard aggregation."""


class BenchmarkRunner(BaseComponent):
    """Execute component × case × repetition matrices reproducibly."""

    @abstractmethod
    def run(self, benchmark: BenchmarkSpec, context: RunContext) -> BenchmarkReport:
        """Run a benchmark and retain every raw observation."""

