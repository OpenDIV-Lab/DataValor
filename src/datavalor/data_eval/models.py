"""Models for quality metrics, evidence, and task-conditioned evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from datavalor.core import ArtifactRef, DataScope, Evidence, TaskContext


class ScoreDirection(str, Enum):
    """How to interpret a numeric score."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    TARGET_IS_BEST = "target_is_best"
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True)
class EvaluationRequest:
    """Requested metrics, granularity, task, and grouping behavior."""

    metrics: tuple[str, ...] = ()
    scope: DataScope = DataScope.DATASET
    task: TaskContext | None = None
    group_by: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricResult:
    """One metric result with explicit meaning and supporting evidence."""

    name: str
    dimension: str
    scope: DataScope
    value: float | None
    direction: ScoreDirection
    unit: str | None = None
    target_id: str | None = None
    statistics: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationReport:
    """Multi-dimensional evaluation output; it is not a price or valuation."""

    product_id: str
    metrics: tuple[MetricResult, ...]
    task_id: str | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskUtilityResult:
    """Observed downstream task performance used as valuation evidence."""

    product_id: str
    task_id: str
    utility: float
    metric: str
    baseline: float | None = None
    uncertainty: Mapping[str, float] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

