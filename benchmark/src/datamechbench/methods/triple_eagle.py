"""Paper-faithful monotone-submodular TripleEagle procurement mechanisms."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

import numpy as np

from ..models import AllocationRecord, MarketOutcome, PaymentRecord, ProcurementInput

_RANDOMIZED_ALPHA = (math.sqrt(13.0) + 1.0) / 2.0
_DETERMINISTIC_ALPHA = math.sqrt(6.0)


class _NormalizedOracle:
    """Set-valued oracle with explicit normalized-query accounting."""

    def __init__(self, case: ProcurementInput) -> None:
        self._case = case
        self._baseline = float(case.utility(()))
        self.query_count = 1
        self._cache: dict[tuple[str, ...], float] = {(): 0.0}

    def value(self, selected: Iterable[str]) -> float:
        key = tuple(sorted(set(selected)))
        if key not in self._cache:
            self._cache[key] = float(self._case.utility(key)) - self._baseline
            self.query_count += 1
        return self._cache[key]


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _offer(
    case: ProcurementInput,
    marginal: float,
    denominator: float,
) -> Decimal:
    if denominator <= 0.0:
        return Decimal("0")
    return case.budget * _decimal(marginal) / _decimal(denominator)


def _lsd_pricing(
    case: ProcurementInput,
    oracle: _NormalizedOracle,
    accepted: list[str],
    candidates: Sequence[str],
    eta: float,
    offers: dict[str, Decimal],
) -> None:
    for seller in candidates:
        current = oracle.value(accepted)
        marginal = oracle.value((*accepted, seller)) - current
        price = _offer(case, marginal, current + eta)
        offers[seller] = price
        if case.reported_costs[seller] <= price:
            accepted.append(seller)


def _largest_budget_feasible_suffix(
    accepted: Sequence[str],
    offers: dict[str, Decimal],
    budget: Decimal,
) -> tuple[str, ...]:
    total = Decimal("0")
    start = len(accepted)
    for index in range(len(accepted) - 1, -1, -1):
        proposed = total + offers[accepted[index]]
        if proposed > budget:
            break
        total = proposed
        start = index
    return tuple(accepted[start:])


def _outcome(
    case: ProcurementInput,
    selected: tuple[str, ...],
    offers: dict[str, Decimal],
    *,
    diagnostics: dict[str, Any],
) -> MarketOutcome:
    payments = tuple(
        PaymentRecord("buyer", seller, offers[seller], "paper_clock_offer", (seller,))
        for seller in selected
    )
    total = sum((payment.amount for payment in payments), Decimal("0"))
    return MarketOutcome(
        selected_ids=selected,
        allocations=tuple(
            AllocationRecord(seller, "buyer", (seller,)) for seller in selected
        ),
        payments=payments,
        diagnostics={
            **diagnostics,
            "offered_prices": {
                seller: str(price) for seller, price in offers.items()
            },
            "payment_semantics": "paper_clock_offer",
            "total_payment": str(total),
            "budget_feasible": total <= case.budget,
        },
    )


def _empty_outcome(
    case: ProcurementInput,
    oracle: _NormalizedOracle,
    *,
    method_id: str,
    alpha: float,
    filtered: list[str],
) -> MarketOutcome:
    return _outcome(
        case,
        (),
        {},
        diagnostics={
            "allocation_rule": method_id,
            "mechanism_branch": "empty_eligible_or_zero_value",
            "alpha": alpha,
            "processing_order": [],
            "accepted_order": [],
            "above_budget_filtered": filtered,
            "utility_query_count": oracle.query_count,
            "suffix_truncated": False,
        },
    )


def _setup(
    case: ProcurementInput,
    *,
    method_id: str,
    alpha: float,
) -> tuple[_NormalizedOracle, list[str], list[str], str | None, float, MarketOutcome | None]:
    oracle = _NormalizedOracle(case)
    eligible = [
        seller
        for seller in case.seller_ids
        if Decimal("0") <= case.reported_costs[seller] <= case.budget
    ]
    filtered = [seller for seller in case.seller_ids if seller not in eligible]
    if not eligible:
        return oracle, eligible, filtered, None, 0.0, _empty_outcome(
            case,
            oracle,
            method_id=method_id,
            alpha=alpha,
            filtered=filtered,
        )
    star = min(eligible, key=lambda seller: (-oracle.value((seller,)), seller))
    star_value = oracle.value((star,))
    if star_value <= 0.0:
        return oracle, eligible, filtered, star, star_value, _empty_outcome(
            case,
            oracle,
            method_id=method_id,
            alpha=alpha,
            filtered=filtered,
        )
    return oracle, eligible, filtered, star, star_value, None


def _randomized(case: ProcurementInput, seed: int) -> MarketOutcome:
    alpha = _RANDOMIZED_ALPHA
    method_id = "TripleEagleRan"
    oracle, eligible, filtered, star, star_value, empty = _setup(
        case, method_id=method_id, alpha=alpha
    )
    if empty is not None:
        return empty
    assert star is not None
    processing_order = [seller for seller in eligible if seller != star]
    accepted: list[str] = []
    offers: dict[str, Decimal] = {}
    _lsd_pricing(
        case,
        oracle,
        accepted,
        processing_order,
        alpha * star_value,
        offers,
    )
    if oracle.value(accepted) >= star_value:
        _lsd_pricing(
            case,
            oracle,
            accepted,
            [star],
            alpha * star_value,
            offers,
        )
        selected = _largest_budget_feasible_suffix(accepted, offers, case.budget)
        branch = "lsd_suffix"
        singleton_probability = alpha / (alpha + 2.0)
        suffix_truncated = len(selected) != len(accepted)
    else:
        singleton_probability = alpha / (alpha + 2.0)
        if np.random.default_rng(seed).random() <= singleton_probability:
            offers[star] = case.budget
            accepted = [star]
            selected = (star,)
            branch = "best_singleton"
        else:
            remaining = case.budget - sum(
                (offers[seller] for seller in accepted), Decimal("0")
            )
            offers[star] = remaining
            if case.reported_costs[star] <= remaining:
                accepted.append(star)
            selected = tuple(accepted)
            branch = "best_effort"
        suffix_truncated = False
    return _outcome(
        case,
        selected,
        offers,
        diagnostics={
            "allocation_rule": method_id,
            "mechanism_branch": branch,
            "alpha": alpha,
            "singleton_probability": singleton_probability,
            "best_singleton": star,
            "processing_order": processing_order,
            "accepted_order": list(accepted),
            "above_budget_filtered": filtered,
            "utility_query_count": oracle.query_count,
            "suffix_truncated": suffix_truncated,
        },
    )


def _deterministic(case: ProcurementInput) -> MarketOutcome:
    alpha = _DETERMINISTIC_ALPHA
    method_id = "TripleEagleDet"
    oracle, eligible, filtered, star, star_value, empty = _setup(
        case, method_id=method_id, alpha=alpha
    )
    if empty is not None:
        return empty
    assert star is not None
    processing_order = [seller for seller in eligible if seller != star]
    remaining = list(eligible)
    first_phase: list[str] = []
    offers: dict[str, Decimal] = {}
    for seller in processing_order:
        marginal = oracle.value((*first_phase, seller)) - oracle.value(first_phase)
        price = _offer(case, marginal, alpha * star_value)
        offers[seller] = price
        if case.reported_costs[seller] <= price:
            first_phase.append(seller)
        remaining.remove(seller)
        if oracle.value(first_phase) >= star_value:
            break
    if oracle.value(first_phase) < star_value:
        offers[star] = case.budget
        accepted = [star]
        selected = (star,)
        branch = "best_singleton"
        suffix_truncated = False
    else:
        accepted = list(first_phase)
        _lsd_pricing(
            case,
            oracle,
            accepted,
            remaining,
            alpha * star_value,
            offers,
        )
        selected = _largest_budget_feasible_suffix(accepted, offers, case.budget)
        branch = "two_phase_suffix"
        suffix_truncated = len(selected) != len(accepted)
    return _outcome(
        case,
        selected,
        offers,
        diagnostics={
            "allocation_rule": method_id,
            "mechanism_branch": branch,
            "alpha": alpha,
            "best_singleton": star,
            "processing_order": processing_order,
            "first_phase_winners": list(first_phase),
            "accepted_order": list(accepted),
            "above_budget_filtered": filtered,
            "utility_query_count": oracle.query_count,
            "suffix_truncated": suffix_truncated,
        },
    )


def allocate_triple_eagle(
    method_id: str,
    case: ProcurementInput,
    seed: int,
) -> MarketOutcome:
    """Execute NeurIPS 2023 Algorithms 1--3 with their theorem parameters."""

    if method_id == "triple_eagle_randomized":
        return _randomized(case, seed)
    if method_id == "triple_eagle_deterministic":
        return _deterministic(case)
    raise KeyError(f"unknown TripleEagle method: {method_id}")


__all__ = ["allocate_triple_eagle"]
