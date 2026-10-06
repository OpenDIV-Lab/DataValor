"""Paper-faithful BFM-VM for budget-feasible valuation procurement.

This module implements Algorithm 2 of Cui et al. (ICML 2026). It follows
the paper pseudocode rather than the accompanying experimental C++ where the
two differ; those differences are recorded by the separate source audit.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from ..models import AllocationRecord, MarketOutcome, PaymentRecord, ProcurementInput

_ALPHA = 1.0 + math.sqrt(3.0)
_CANDIDATE_SEQUENCE_COUNT = 2


class _NormalizedOracle:
    def __init__(self, case: ProcurementInput) -> None:
        self._case = case
        self._position = {
            seller: index for index, seller in enumerate(case.seller_ids)
        }
        self._baseline = float(case.utility(()))
        self._cache: dict[tuple[str, ...], float] = {(): 0.0}
        self.query_count = 1

    def _key(self, selected: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted(set(selected), key=self._position.__getitem__))

    def value(self, selected: Iterable[str]) -> float:
        key = self._key(selected)
        if key not in self._cache:
            self._cache[key] = float(self._case.utility(key)) - self._baseline
            self.query_count += 1
        return self._cache[key]

    def marginal(self, selected: Iterable[str], seller: str) -> float:
        selected_tuple = tuple(selected)
        return self.value((*selected_tuple, seller)) - self.value(selected_tuple)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _empty_outcome(
    *,
    branch: str,
    eligible: list[str],
    filtered: list[str],
    query_count: int,
) -> MarketOutcome:
    return MarketOutcome(
        diagnostics={
            "allocation_rule": "BFM-VM",
            "paper_algorithm": "Cui et al. 2026 Algorithm 2",
            "mechanism_branch": branch,
            "alpha": _ALPHA,
            "candidate_sequence_count": _CANDIDATE_SEQUENCE_COUNT,
            "eligible_sellers": eligible,
            "above_budget_filtered": filtered,
            "round_count": 0,
            "utility_query_count": query_count,
            "payment_semantics": "paper_descending_clock_offer",
            "total_payment": "0",
            "budget_feasible": True,
        }
    )


def allocate_bfm_vm(case: ProcurementInput) -> MarketOutcome:
    """Run paper Algorithm 2 with stable input-order tie breaking."""

    oracle = _NormalizedOracle(case)
    eligible = [
        seller
        for seller in case.seller_ids
        if Decimal("0") <= case.reported_costs[seller] <= case.budget
    ]
    filtered = [seller for seller in case.seller_ids if seller not in eligible]
    if not eligible:
        return _empty_outcome(
            branch="empty_eligible_set",
            eligible=eligible,
            filtered=filtered,
            query_count=oracle.query_count,
        )

    singleton_values = {seller: oracle.value((seller,)) for seller in eligible}
    best_singleton = max(eligible, key=singleton_values.__getitem__)
    rho = singleton_values[best_singleton]
    if rho <= 0.0:
        return _empty_outcome(
            branch="nonpositive_singleton_domain",
            eligible=eligible,
            filtered=filtered,
            query_count=oracle.query_count,
        )

    active = list(eligible)
    prices = {seller: case.budget for seller in active}
    owners: dict[str, int | None] = {seller: None for seller in active}
    owners[best_singleton] = 0
    previous: list[list[str]] = [[best_singleton], []]
    current: list[list[str]] = [[], []]
    round_count = 1
    break_count = 0
    owner_locked_decisions = 0

    # Theorem 5.4 bounds the outer loop by O(log n). The guard is defensive
    # and is not used as an alternative stopping rule.
    maximum_rounds = 4 + math.ceil(
        math.log(max(2, 2 * len(eligible)), _ALPHA)
    )
    while True:
        round_count += 1
        if round_count > maximum_rounds:
            raise RuntimeError("BFM-VM exceeded the paper outer-loop bound")
        rho *= _ALPHA
        current = [[], []]
        previous_union = set(previous[0]) | set(previous[1])
        for seller in [item for item in active if item not in previous_union]:
            marginals = [
                oracle.marginal(current[index], seller)
                for index in range(_CANDIDATE_SEQUENCE_COUNT)
            ]
            owner = owners[seller]
            if owner is None:
                candidate_index = max(
                    range(_CANDIDATE_SEQUENCE_COUNT),
                    key=lambda index: marginals[index],
                )
            else:
                candidate_index = owner
                owner_locked_decisions += 1

            offered = (
                case.budget
                * _decimal(marginals[candidate_index])
                / _decimal(rho)
            )
            prices[seller] = min(prices[seller], offered)
            if case.reported_costs[seller] > prices[seller]:
                active.remove(seller)
                continue
            proposed = (*current[candidate_index], seller)
            if oracle.value(proposed) > rho:
                break_count += 1
                break
            current[candidate_index].append(seller)
            if owners[seller] is None:
                owners[seller] = candidate_index

        covered = (
            set(previous[0])
            | set(previous[1])
            | set(current[0])
            | set(current[1])
        )
        if all(seller in covered for seller in active):
            break
        previous = current

    candidates = (previous[0], current[0], previous[1], current[1])
    selected_list = max(candidates, key=oracle.value)
    selected = tuple(selected_list)
    payments = tuple(
        PaymentRecord(
            "buyer",
            seller,
            prices[seller],
            "paper_descending_clock_offer",
            (seller,),
        )
        for seller in selected
    )
    total_payment = sum((payment.amount for payment in payments), Decimal("0"))
    diagnostics: dict[str, Any] = {
        "allocation_rule": "BFM-VM",
        "paper_algorithm": "Cui et al. 2026 Algorithm 2",
        "mechanism_branch": "terminal_best_last_two_rounds",
        "alpha": _ALPHA,
        "candidate_sequence_count": _CANDIDATE_SEQUENCE_COUNT,
        "best_singleton": best_singleton,
        "eligible_sellers": eligible,
        "above_budget_filtered": filtered,
        "round_count": round_count,
        "break_count": break_count,
        "owner_locked_decisions": owner_locked_decisions,
        "owner_sequence": {
            seller: owners[seller]
            for seller in eligible
            if owners[seller] is not None
        },
        "offered_prices": {seller: str(prices[seller]) for seller in active},
        "utility_query_count": oracle.query_count,
        "payment_semantics": "paper_descending_clock_offer",
        "total_payment": str(total_payment),
        "budget_feasible": total_payment <= case.budget,
    }
    return MarketOutcome(
        selected_ids=selected,
        allocations=tuple(
            AllocationRecord(seller, "buyer", (seller,)) for seller in selected
        ),
        payments=payments,
        diagnostics=diagnostics,
    )


__all__ = ["allocate_bfm_vm"]
