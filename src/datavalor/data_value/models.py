"""Models for task-aware, user-aware, and contribution-based valuation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from datavalor.core import (
    ActorProfile,
    ArtifactRef,
    CostContext,
    DataProduct,
    DataScope,
    RightsBundle,
    TaskContext,
)


class ValuationMode(str, Enum):
    """High-level assumptions under which a valuation method operates."""

    MODEL_DEPENDENT = "model_dependent"
    MODEL_AGNOSTIC = "model_agnostic"
    TASK_SPECIFIC = "task_specific"
    MARKET_ORIENTED = "market_oriented"


@dataclass(frozen=True)
class ValuationTarget:
    """Sample, group, dataset, or product whose value is estimated."""

    target_id: str
    product_id: str
    scope: DataScope
    members: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationRequest:
    """All explicit context required to estimate value without inferring a price."""

    product: DataProduct
    targets: tuple[ValuationTarget, ...]
    buyer: ActorProfile | None = None
    task: TaskContext | None = None
    rights: RightsBundle | None = None
    costs: CostContext | None = None
    evaluation_artifacts: tuple[ArtifactRef, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValueEstimate:
    """One value estimate with components, uncertainty, and explanation."""

    target_id: str
    value: float
    unit: str
    currency: str | None = None
    components: Mapping[str, float] = field(default_factory=dict)
    uncertainty: Mapping[str, float] = field(default_factory=dict)
    explanation: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationReport:
    """Estimates produced under one explicit valuation method and context."""

    product_id: str
    method: str
    mode: ValuationMode
    estimates: tuple[ValueEstimate, ...]
    buyer_id: str | None = None
    task_id: str | None = None
    converged: bool | None = None
    iterations: int | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContributionRequest:
    """Coalitional or marginal-contribution valuation request."""

    product: DataProduct
    units: tuple[ValuationTarget, ...]
    task: TaskContext
    method_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContributionReport:
    """Per-unit contributions and convergence evidence."""

    product_id: str
    method: str
    contributions: tuple[ValueEstimate, ...]
    utility_calls: int | None = None
    converged: bool | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrainingReport:
    """Metadata from fitting a learned valuation method."""

    method: str
    observations: int
    converged: bool | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

