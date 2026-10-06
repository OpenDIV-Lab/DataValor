"""Stable case and result contracts for the mechanism benchmark."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable, Mapping

CoalitionUtility = Callable[[tuple[str, ...]], float]


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} IDs must be unique")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if callable(value):
        return None
    return value


@dataclass(frozen=True)
class MethodSpec:
    method_id: str
    track: str
    role: str
    source: str
    version: str
    family_id: str = ""
    implementation_kind: str = "native"
    stochastic: bool = False
    requires: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()
    assumptions: tuple[str, ...] = ()
    supported_case_types: frozenset[str] = frozenset()
    provenance_kind: str = "paper_variant"
    reference_keys: tuple[str, ...] = ()
    algorithm_location: str = "legacy registration; see mechanism catalog"
    deviations: tuple[str, ...] = ()
    estimand: str = "not_applicable"

    def __post_init__(self) -> None:
        if self.track not in {"valuation", "procurement", "trading"}:
            raise ValueError(f"unsupported track: {self.track}")
        if self.role not in {"baseline", "method", "oracle"}:
            raise ValueError(f"unsupported role: {self.role}")
        if not self.method_id:
            raise ValueError("method_id must be non-empty")
        if not self.family_id:
            object.__setattr__(self, "family_id", self.method_id)
        if self.implementation_kind not in {"native", "external_adapter"}:
            raise ValueError(f"unsupported implementation kind: {self.implementation_kind}")
        provenance_kinds = {
            "paper_exact",
            "official_adapter",
            "paper_variant",
            "project_implementation",
            "common_baseline",
            "allocation_oracle",
            "diagnostic_reference",
        }
        if self.provenance_kind not in provenance_kinds:
            raise ValueError(f"unsupported provenance kind: {self.provenance_kind}")
        if not self.algorithm_location:
            raise ValueError("algorithm_location must be non-empty")
        if self.estimand not in {
            "ordinary_shapley",
            "alternative_estimand",
            "not_applicable",
        }:
            raise ValueError(f"unsupported estimand: {self.estimand}")

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


@dataclass(frozen=True)
class ValuationCase:
    case_id: str
    owner_ids: tuple[str, ...]
    utility: CoalitionUtility
    case_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    truth_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _unique(self.owner_ids, "owner")


@dataclass(frozen=True)
class ProcurementInput:
    seller_ids: tuple[str, ...]
    reported_costs: Mapping[str, Decimal]
    budget: Decimal
    utility: CoalitionUtility
    seller_values: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _unique(self.seller_ids, "seller")
        if set(self.reported_costs) != set(self.seller_ids):
            raise ValueError("reported costs must match seller IDs")
        if not self.budget.is_finite() or self.budget < 0:
            raise ValueError("budget must be finite and non-negative")


@dataclass(frozen=True)
class ProcurementCase:
    case_id: str
    public: ProcurementInput
    true_costs: Mapping[str, Decimal]
    case_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    attack_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeInput:
    product_id: str
    buyer_ids: tuple[str, ...]
    seller_ids: tuple[str, ...]
    bids: Mapping[str, Decimal]
    asks: Mapping[str, Decimal]
    posted_price: Decimal | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _unique(self.buyer_ids, "buyer")
        _unique(self.seller_ids, "seller")
        if set(self.bids) != set(self.buyer_ids):
            raise ValueError("bids must match buyer IDs")
        if set(self.asks) != set(self.seller_ids):
            raise ValueError("asks must match seller IDs")


@dataclass(frozen=True)
class TradeCase:
    case_id: str
    public: TradeInput
    true_values: Mapping[str, Decimal]
    true_costs: Mapping[str, Decimal]
    case_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    attack_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationOutput:
    scores: Mapping[str, float]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    utility_calls: int | None = None


@dataclass(frozen=True)
class ValuationMechanismDecision:
    """Method-agnostic downstream decision induced by one valuation vector."""

    selected_ids: tuple[str, ...]
    payments: Mapping[str, Decimal] = field(default_factory=dict)
    welfare: float = 0.0
    stop_index: int | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AllocationRecord:
    actor_id: str
    counterparty_id: str | None = None
    product_ids: tuple[str, ...] = ()
    quantity: Decimal = Decimal("1")
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentRecord:
    payer_id: str
    payee_id: str
    amount: Decimal
    reason: str
    product_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketOutcome:
    selected_ids: tuple[str, ...] = ()
    allocations: tuple[AllocationRecord, ...] = ()
    payments: tuple[PaymentRecord, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkResult:
    run_id: str
    track: str
    method_id: str
    case_id: str
    seed: int
    status: str
    metrics: Mapping[str, Any]
    runtime_seconds: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    outcome: Mapping[str, Any] | None = None
    schema_version: str = "1.1"

    def __post_init__(self) -> None:
        if self.status not in {"completed", "skipped", "failed"}:
            raise ValueError(f"unsupported status: {self.status}")
        if not math.isfinite(self.runtime_seconds) or self.runtime_seconds < 0:
            raise ValueError("runtime_seconds must be finite and non-negative")
        if self.schema_version == "1.2":
            if self.status == "completed" and not isinstance(self.outcome, Mapping):
                raise ValueError("completed schema 1.2 result requires outcome")
            if self.status != "completed" and self.outcome is not None:
                raise ValueError("non-completed result cannot carry outcome")

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))


__all__ = [
    "AllocationRecord",
    "BenchmarkResult",
    "CoalitionUtility",
    "MarketOutcome",
    "MethodSpec",
    "PaymentRecord",
    "ProcurementCase",
    "ProcurementInput",
    "TradeCase",
    "TradeInput",
    "ValuationCase",
    "ValuationMechanismDecision",
    "ValuationOutput",
]
