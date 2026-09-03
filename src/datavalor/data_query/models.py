"""Models for governed natural-language queries and data agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from datavalor.core import ActorProfile, ArtifactRef, DataProduct, Evidence, TaskContext


class AuthorizationDecision(str, Enum):
    """Query-specific authorization result evaluated before execution."""

    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"


@dataclass(frozen=True)
class QueryRequest:
    """Natural-language or structured request against governed products."""

    request_id: str
    actor: ActorProfile
    question: str
    products: tuple[DataProduct, ...]
    task: TaskContext | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    max_rows: int | None = None


@dataclass(frozen=True)
class QueryAuthorization:
    """Policy gate evaluated before planning and execution."""

    request_id: str
    decision: AuthorizationDecision
    approved_products: tuple[str, ...] = ()
    policies: tuple[str, ...] = ()
    restrictions: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryPlanStep:
    """One inspectable retrieval, transformation, or computation step."""

    step_id: str
    operation: str
    product_ids: tuple[str, ...] = ()
    statement: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryPlan:
    """Authorized execution plan generated from a query request."""

    request_id: str
    steps: tuple[QueryPlanStep, ...]
    authorization: QueryAuthorization
    planner: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryTraceEvent:
    """Auditable event emitted during planning, execution, or guarding."""

    stage: str
    event: str
    details: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    """Governed result with explicit trace and optional tabular records."""

    request_id: str
    answer: str | None = None
    records: tuple[Mapping[str, Any], ...] = ()
    columns: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    trace: tuple[QueryTraceEvent, ...] = ()
    truncated: bool = False
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UsageEvent:
    """Metered consumption emitted after a governed delivery or query."""

    event_id: str
    product_id: str
    buyer_id: str
    operation: str
    quantity: float = 1.0
    records_returned: int = 0
    compute_seconds: float | None = None
    privacy_budget: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
