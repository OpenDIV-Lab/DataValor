"""Frozen downstream settings shared by every valuation method."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class InapplicabilityReason:
    code: str
    detail: str


@dataclass(frozen=True)
class ApplicableMethod:
    method_id: str
    estimand: str
    na_reason: InapplicabilityReason | None = None


@dataclass(frozen=True)
class ValuationMechanismSetting:
    setting_id: str
    mechanism: str
    owner_ids: tuple[str, ...]
    methods: tuple[ApplicableMethod, ...]
    primary: bool = True
    costs: Mapping[str, Decimal] = field(default_factory=dict)
    bids: Mapping[str, Decimal] = field(default_factory=dict)
    budget: Decimal = Decimal("10")
    top_k: int = 3
    reserve: float = 0.0
    target_utility: float = 8.0
    duplicate_owners: frozenset[str] = frozenset()
    noisy_owners: frozenset[str] = frozenset()


def _methods() -> tuple[ApplicableMethod, ...]:
    return (
        ApplicableMethod("shapley_exact_low_residual", "ordinary_shapley"),
        ApplicableMethod("shapiq_svarm", "ordinary_shapley"),
        ApplicableMethod("official_stratified_svarm", "ordinary_shapley"),
        ApplicableMethod("shapiq_kernel_shap", "ordinary_shapley"),
        ApplicableMethod("shapley_stratified", "ordinary_shapley"),
        ApplicableMethod("beta_shapley", "alternative_estimand"),
        ApplicableMethod(
            "asss_a",
            "ordinary_shapley",
            InapplicabilityReason(
                "official_implementation_unavailable",
                "No auditable official implementation or complete algorithm was located.",
            ),
        ),
    )


def valuation_mechanism_settings() -> tuple[ValuationMechanismSetting, ...]:
    owners = tuple(f"o{index}" for index in range(8))
    costs = {owner: Decimal(str(1 + (index % 4))) for index, owner in enumerate(owners)}
    bids = {owner: Decimal(str(3 + index)) for index, owner in enumerate(owners)}
    common = {"owner_ids": owners, "methods": _methods(), "costs": costs, "bids": bids}
    return (
        ValuationMechanismSetting("mech-topk", "top_k_acquisition", top_k=3, **common),
        ValuationMechanismSetting(
            "mech-procurement", "budgeted_procurement", budget=Decimal("12"), **common
        ),
        ValuationMechanismSetting(
            "mech-revenue", "revenue_allocation", budget=Decimal("100"), **common
        ),
        ValuationMechanismSetting(
            "mech-reserve", "reserve_admission", reserve=3.5, **common
        ),
        ValuationMechanismSetting(
            "mech-corruption",
            "corruption_exclusion",
            top_k=5,
            noisy_owners=frozenset({"o1", "o6"}),
            **common,
        ),
        ValuationMechanismSetting(
            "mech-replication",
            "replication_attack",
            budget=Decimal("100"),
            duplicate_owners=frozenset({"o6", "o7"}),
            **common,
        ),
        ValuationMechanismSetting(
            "mech-split",
            "split_attack",
            top_k=4,
            duplicate_owners=frozenset({"o6", "o7"}),
            **common,
        ),
        ValuationMechanismSetting(
            "mech-sequential",
            "sequential_acquisition",
            target_utility=12.0,
            **common,
        ),
    )


__all__ = [
    "ApplicableMethod",
    "InapplicabilityReason",
    "ValuationMechanismSetting",
    "valuation_mechanism_settings",
]
