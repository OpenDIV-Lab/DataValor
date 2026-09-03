"""Models for cross-module, reproducible benchmark experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from datavalor.core import ArtifactRef


@dataclass(frozen=True)
class BenchmarkCase:
    """One immutable experimental case and its input artifacts."""

    case_id: str
    inputs: Mapping[str, ArtifactRef]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    expected: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkSpec:
    """Components, cases, repetitions, and metrics defining a benchmark."""

    benchmark_id: str
    components: tuple[str, ...]
    cases: tuple[BenchmarkCase, ...]
    metrics: tuple[str, ...]
    repetitions: int = 1
    seed: int = 0
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkObservation:
    """One component/case/repetition result before aggregation."""

    component: str
    case_id: str
    repetition: int
    outputs: tuple[ArtifactRef, ...]
    measurements: Mapping[str, float | int | bool | None] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkReport:
    """Raw observations and aggregates with no hidden leaderboard filtering."""

    benchmark_id: str
    observations: tuple[BenchmarkObservation, ...]
    aggregates: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

