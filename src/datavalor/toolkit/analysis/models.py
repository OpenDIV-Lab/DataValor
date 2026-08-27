"""Models for statistical analysis, comparison, and frontier construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from datavalor.core import ArtifactRef


@dataclass(frozen=True)
class AnalysisRequest:
    """Artifact inputs, metrics, grouping, and statistical options."""

    artifacts: tuple[ArtifactRef, ...]
    metrics: tuple[str, ...]
    group_by: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisResult:
    """Tables, statistics, warnings, and derived artifacts."""

    analyzer: str
    statistics: Mapping[str, Any]
    artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonRequest:
    """Named baseline and candidates for paired or unpaired comparison."""

    baseline: str
    candidates: tuple[str, ...]
    artifacts: tuple[ArtifactRef, ...]
    metrics: tuple[str, ...]
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonResult:
    """Effect estimates, uncertainty, and assumption diagnostics."""

    baseline: str
    comparisons: Mapping[str, Any]
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

