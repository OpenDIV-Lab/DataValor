"""Additional budgeted procurement allocation and payment rules."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import numpy as np

from ..models import (
    AllocationRecord,
    MarketOutcome,
    PaymentRecord,
    ProcurementInput,
)
from .bfm_vm import allocate_bfm_vm
from .triple_eagle import allocate_triple_eagle

SelectionRule = Callable[[ProcurementInput, Mapping[str, Decimal]], tuple[str, ...]]
_EXACT_ORACLE_CACHE: dict[
    tuple[tuple[str, ...], int],
    tuple[Callable[..., Any], np.ndarray, np.ndarray],
] = {}


def _payment(seller: str, amount: Decimal, reason: str) -> PaymentRecord:
    return PaymentRecord("buyer", seller, amount, reason, (seller,))


def _outcome(
    selected: tuple[str, ...],
    payments: Mapping[str, Decimal] | None = None,
    *,
    reason: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> MarketOutcome:
    amounts = payments or {}
    return MarketOutcome(
        selected_ids=selected,
        allocations=tuple(AllocationRecord(seller, "buyer", (seller,)) for seller in selected),
        payments=tuple(_payment(seller, amounts[seller], reason) for seller in selected if seller in amounts),
        diagnostics=dict(diagnostics or {}),
    )


def _pay_as_bid(case: ProcurementInput, selected: tuple[str, ...], reason: str) -> MarketOutcome:
    return _outcome(
        selected,
        {seller: case.reported_costs[seller] for seller in selected},
        reason=reason,
        diagnostics={"payment_semantics": "pay_as_bid"},
    )


def _ordered_budget_selection(
    case: ProcurementInput, key: Callable[[str], tuple[Any, ...]]
) -> tuple[str, ...]:
    remaining = case.budget
    selected: list[str] = []
    for seller in sorted(case.seller_ids, key=key):
        cost = case.reported_costs[seller]
        if cost >= 0 and cost <= remaining:
            selected.append(seller)
            remaining -= cost
    return tuple(selected)


def _marginal_greedy_rule(
    case: ProcurementInput,
    costs: Mapping[str, Decimal],
    *,
    budget_factor: Decimal,
) -> tuple[str, ...]:
    selected: list[str] = []
    baseline = float(case.utility(()))
    current = baseline
    while True:
        candidates = []
        for seller in case.seller_ids:
            cost = costs[seller]
            if seller in selected or cost <= 0 or cost > case.budget:
                continue
            value = float(case.utility(tuple((*selected, seller))))
            marginal = value - current
            if marginal > 0:
                candidates.append((marginal / float(cost), marginal, seller, value))
        if not candidates:
            break
        _, marginal, seller, value = min(
            candidates, key=lambda item: (-item[0], -item[1], item[2])
        )
        total_value = value - baseline
        allowed = budget_factor * case.budget * Decimal(str(marginal)) / Decimal(str(total_value))
        if costs[seller] > allowed:
            break
        selected.append(seller)
        current = value
    return tuple(selected)


def _threshold_payments(
    case: ProcurementInput,
    winners: tuple[str, ...],
    rule: SelectionRule,
) -> dict[str, Decimal]:
    payments: dict[str, Decimal] = {}
    for winner in winners:
        low = case.reported_costs[winner]
        high = case.budget
        if winner in rule(case, {**case.reported_costs, winner: high}):
            payments[winner] = high
            continue
        for _ in range(64):
            midpoint = (low + high) / Decimal("2")
            reports = {**case.reported_costs, winner: midpoint}
            if winner in rule(case, reports):
                low = midpoint
            else:
                high = midpoint
        payments[winner] = low
    total = sum(payments.values(), Decimal("0"))
    if total > case.budget and total - case.budget <= Decimal("1e-12"):
        final = winners[-1]
        payments[final] -= total - case.budget
    return payments


def _reverse(case: ProcurementInput, *, second_price: bool) -> MarketOutcome:
    ranked = sorted(case.seller_ids, key=lambda seller: (case.reported_costs[seller], seller))
    if not ranked or case.reported_costs[ranked[0]] > case.budget:
        return _outcome((), reason="reverse_auction")
    winner = ranked[0]
    if second_price:
        price = min(
            case.budget,
            case.reported_costs[ranked[1]] if len(ranked) > 1 else case.budget,
        )
        reason = "reverse_second_price"
    else:
        price = case.reported_costs[winner]
        reason = "reverse_first_price"
    return _outcome((winner,), {winner: price}, reason=reason)


def _posted(case: ProcurementInput, *, scaled: bool) -> MarketOutcome:
    if scaled:
        positive = {seller: max(0.0, float(case.seller_values.get(seller, 0.0))) for seller in case.seller_ids}
        total_value = sum(positive.values())
        offers = {
            seller: case.budget * Decimal(str(value / total_value)) if total_value else Decimal("0")
            for seller, value in positive.items()
        }
        reason = "value_scaled_posted_offer"
    else:
        offer = case.budget / max(1, len(case.seller_ids))
        offers = {seller: offer for seller in case.seller_ids}
        reason = "uniform_posted_offer"
    selected = tuple(
        seller for seller in case.seller_ids if case.reported_costs[seller] <= offers[seller]
    )
    return _outcome(selected, {seller: offers[seller] for seller in selected}, reason=reason)


def _proportional(case: ProcurementInput, *, half_budget: bool) -> MarketOutcome:
    factor = Decimal("0.5") if half_budget else Decimal("1")

    def rule(public: ProcurementInput, costs: Mapping[str, Decimal]) -> tuple[str, ...]:
        return _marginal_greedy_rule(public, costs, budget_factor=factor)

    winners = rule(case, case.reported_costs)
    payments = _threshold_payments(case, winners, rule)
    return _outcome(
        winners,
        payments,
        reason="critical_payment",
        diagnostics={
            "allocation_rule": "cgl_half_budget" if half_budget else "generalized_proportional_share",
            "budget_feasible": sum(payments.values(), Decimal("0")) <= case.budget,
        },
    )


def _best_singleton_rule(
    case: ProcurementInput, costs: Mapping[str, Decimal]
) -> tuple[str, ...]:
    eligible = [seller for seller in case.seller_ids if costs[seller] <= case.budget]
    if not eligible:
        return ()
    baseline = float(case.utility(()))
    winner = min(
        eligible,
        key=lambda seller: (-(float(case.utility((seller,))) - baseline), seller),
    )
    return (winner,)


def _utility_gain(case: ProcurementInput, selected: tuple[str, ...]) -> float:
    """Normalize a paper valuation so that v(empty)=0."""

    return float(case.utility(selected)) - float(case.utility(()))


def _cgl_randomized(case: ProcurementInput, seed: int) -> MarketOutcome:
    greedy_branch = np.random.default_rng(seed).random() < 0.6
    if greedy_branch:
        outcome = _proportional(case, half_budget=True)
        return MarketOutcome(
            selected_ids=outcome.selected_ids,
            allocations=outcome.allocations,
            payments=outcome.payments,
            diagnostics={
                **outcome.diagnostics,
                "allocation_rule": "CGL-Random-Mechanism-SM",
                "mixture_branch": "greedy_sm",
                "greedy_probability": 0.6,
                "greedy_budget_fraction": "0.5",
            },
        )
    winners = _best_singleton_rule(case, case.reported_costs)
    payments = _threshold_payments(case, winners, _best_singleton_rule)
    return _outcome(
        winners,
        payments,
        reason="critical_payment",
        diagnostics={
            "allocation_rule": "CGL-Random-Mechanism-SM",
            "mixture_branch": "best_singleton",
            "greedy_probability": 0.6,
            "budget_feasible": True,
        },
    )


_CGL_SINGLETON_COMPARISON = (
    1.0 + 4.0 * math.e + math.sqrt(1.0 + 24.0 * math.e * math.e)
) / (2.0 * (math.e - 1.0))


def _cgl_deterministic_rule(
    case: ProcurementInput,
    costs: Mapping[str, Decimal],
) -> tuple[str, ...]:
    best = _best_singleton_rule(case, costs)
    best_value = _utility_gain(case, best) if best else 0.0
    other_optimum = _exact_optimum_value(case, costs, excluded=frozenset(best))
    if best and _CGL_SINGLETON_COMPARISON * best_value >= other_optimum:
        return best
    return _marginal_greedy_rule(case, costs, budget_factor=Decimal("0.5"))


def _cgl_deterministic(case: ProcurementInput) -> MarketOutcome:
    best = _best_singleton_rule(case, case.reported_costs)
    best_value = _utility_gain(case, best) if best else 0.0
    other_optimum = _exact_optimum_value(
        case,
        case.reported_costs,
        excluded=frozenset(best),
    )
    singleton_branch = bool(
        best and _CGL_SINGLETON_COMPARISON * best_value >= other_optimum
    )
    winners = _cgl_deterministic_rule(case, case.reported_costs)
    payments = _threshold_payments(case, winners, _cgl_deterministic_rule)
    return _outcome(
        winners,
        payments,
        reason="critical_payment",
        diagnostics={
            "allocation_rule": "CGL-Mechanism-SM",
            "mechanism_branch": "best_singleton" if singleton_branch else "greedy_sm",
            "singleton_comparison_constant": _CGL_SINGLETON_COMPARISON,
            "greedy_budget_fraction": "0.5",
            "oracle": "exact_optimum_without_best_singleton",
            "payment_computation": "64_step_critical_threshold_bisection",
            "budget_feasible": sum(payments.values(), Decimal("0")) <= case.budget,
        },
    )


def _jt_greedy_tm_rule(
    case: ProcurementInput,
    costs: Mapping[str, Decimal],
    *,
    gamma: float,
) -> tuple[str, ...]:
    selected: list[str] = []
    baseline = float(case.utility(()))
    current = baseline
    while True:
        candidates: list[tuple[float, float, str, float]] = []
        for seller in case.seller_ids:
            if seller in selected or costs[seller] < 0 or costs[seller] > case.budget:
                continue
            proposed = float(case.utility(tuple((*selected, seller))))
            marginal = proposed - current
            if marginal <= 0:
                continue
            bang = math.inf if costs[seller] == 0 else marginal / float(costs[seller])
            candidates.append((bang, marginal, seller, proposed))
        if not candidates:
            break
        _, marginal, seller, proposed = min(
            candidates, key=lambda item: (-item[0], -item[1], item[2])
        )
        left = float(costs[seller]) / marginal
        cumulative_value = proposed - baseline
        right = (
            gamma * float(case.budget) / cumulative_value
            if cumulative_value > 0
            else 0.0
        )
        if left > right:
            break
        selected.append(seller)
        current = proposed
    return tuple(selected)


def _exact_optimum_value(
    case: ProcurementInput,
    costs: Mapping[str, Decimal],
    *,
    excluded: frozenset[str] = frozenset(),
) -> float:
    cache_key = (case.seller_ids, id(case.utility))
    cached = _EXACT_ORACLE_CACHE.get(cache_key)
    if cached is None or cached[0] is not case.utility:
        subset_ids = np.arange(1 << len(case.seller_ids), dtype=np.uint64)
        bit_ids = np.arange(len(case.seller_ids), dtype=np.uint64)
        incidence = ((subset_ids[:, None] >> bit_ids) & 1).astype(float)
        utilities = np.asarray(
            [
                float(
                    case.utility(
                        tuple(
                            seller
                            for index, seller in enumerate(case.seller_ids)
                            if row[index]
                        )
                    )
                )
                for row in incidence
            ],
            dtype=float,
        )
        cached = (case.utility, incidence, utilities)
        _EXACT_ORACLE_CACHE[cache_key] = cached
    _, incidence, utilities = cached
    cost_vector = np.asarray([float(costs[seller]) for seller in case.seller_ids])
    feasible = incidence @ cost_vector <= float(case.budget) + 1e-12
    if excluded:
        for seller in excluded:
            feasible &= incidence[:, case.seller_ids.index(seller)] == 0
    return float(np.max(utilities[feasible]) - utilities[0])


def _jt_greedy_eom_rule(
    case: ProcurementInput,
    costs: Mapping[str, Decimal],
    *,
    alpha: float,
) -> tuple[str, ...]:
    optimum = _exact_optimum_value(case, costs)
    selected: list[str] = []
    baseline = float(case.utility(()))
    current = baseline
    while True:
        candidates: list[tuple[float, float, str, float]] = []
        for seller in case.seller_ids:
            if seller in selected or costs[seller] < 0 or costs[seller] > case.budget:
                continue
            proposed = float(case.utility(tuple((*selected, seller))))
            marginal = proposed - current
            if marginal <= 0:
                continue
            bang = math.inf if costs[seller] == 0 else marginal / float(costs[seller])
            candidates.append((bang, marginal, seller, proposed))
        if not candidates:
            break
        _, _, seller, proposed = min(
            candidates, key=lambda item: (-item[0], -item[1], item[2])
        )
        if proposed - baseline > alpha * optimum:
            break
        selected.append(seller)
        current = proposed
    return tuple(selected)


def _jt_outcome(
    case: ProcurementInput,
    rule: SelectionRule,
    *,
    diagnostics: Mapping[str, Any],
) -> MarketOutcome:
    winners = rule(case, case.reported_costs)
    payments = _threshold_payments(case, winners, rule)
    return _outcome(
        winners,
        payments,
        reason="critical_payment",
        diagnostics={
            **diagnostics,
            "budget_feasible": sum(payments.values(), Decimal("0")) <= case.budget,
            "payment_computation": "64_step_critical_threshold_bisection",
        },
    )


def _jt_mechanism(
    method_id: str,
    case: ProcurementInput,
    seed: int,
    params: Mapping[str, Any],
) -> MarketOutcome:
    gamma = float(params.get("gamma", 0.5))
    alpha = float(params.get("alpha", 0.5))
    if method_id == "jt_greedy_tm":
        def rule(
            public: ProcurementInput, costs: Mapping[str, Decimal]
        ) -> tuple[str, ...]:
            return _jt_greedy_tm_rule(public, costs, gamma=gamma)

        return _jt_outcome(case, rule, diagnostics={"allocation_rule": "Greedy-TM", "gamma": gamma})
    if method_id == "jt_random_tm":
        greedy_branch = np.random.default_rng(seed).random() < (gamma + 1.0) / (gamma + 2.0)
        rule = (
            (lambda public, costs: _jt_greedy_tm_rule(public, costs, gamma=gamma))
            if greedy_branch
            else _best_singleton_rule
        )
        return _jt_outcome(
            case,
            rule,
            diagnostics={
                "allocation_rule": "Random-TM",
                "gamma": gamma,
                "mixture_branch": "greedy_tm" if greedy_branch else "best_singleton",
            },
        )
    if method_id == "jt_random_eom":
        greedy_branch = np.random.default_rng(seed).random() < 0.5
        rule = (
            (lambda public, costs: _jt_greedy_eom_rule(public, costs, alpha=alpha))
            if greedy_branch
            else _best_singleton_rule
        )
        return _jt_outcome(
            case,
            rule,
            diagnostics={
                "allocation_rule": "Random-EOM",
                "alpha": alpha,
                "mixture_branch": "greedy_eom" if greedy_branch else "best_singleton",
                "greedy_probability": 0.5,
            },
        )
    if method_id == "jt_deterministic_eom":
        best = _best_singleton_rule(case, case.reported_costs)
        best_owner = best[0] if best else None
        best_value = _utility_gain(case, best) if best else 0.0
        other_optimum = _exact_optimum_value(
            case,
            case.reported_costs,
            excluded=frozenset(best),
        )
        singleton_branch = best_owner is not None and best_value >= (
            (math.sqrt(17.0) - 3.0) / 4.0
        ) * other_optimum

        def deterministic_rule(
            public: ProcurementInput, costs: Mapping[str, Decimal]
        ) -> tuple[str, ...]:
            local_best = _best_singleton_rule(public, costs)
            local_value = _utility_gain(public, local_best) if local_best else 0.0
            local_optimum = _exact_optimum_value(
                public, costs, excluded=frozenset(local_best)
            )
            if local_best and local_value >= ((math.sqrt(17.0) - 3.0) / 4.0) * local_optimum:
                return local_best
            return _jt_greedy_eom_rule(public, costs, alpha=0.5)

        return _jt_outcome(
            case,
            deterministic_rule,
            diagnostics={
                "allocation_rule": "Deterministic-EOM",
                "alpha": 0.5,
                "eom_branch": "best_singleton" if singleton_branch else "greedy_eom",
            },
        )
    raise KeyError(method_id)


def _vcg(case: ProcurementInput) -> MarketOutcome:
    def best(excluded: str | None = None):
        available = tuple(seller for seller in case.seller_ids if seller != excluded)
        best_subset: tuple[str, ...] = ()
        best_welfare = float(case.utility(()))
        for size in range(len(available) + 1):
            for subset in itertools.combinations(available, size):
                welfare = float(case.utility(subset)) - sum(
                    float(case.reported_costs[seller]) for seller in subset
                )
                if welfare > best_welfare or (welfare == best_welfare and subset < best_subset):
                    best_subset, best_welfare = subset, welfare
        return best_subset, best_welfare

    selected, welfare = best()
    payments = {}
    for seller in selected:
        _, without = best(seller)
        amount = case.reported_costs[seller] + Decimal(str(welfare - without))
        payments[seller] = max(case.reported_costs[seller], amount)
    total = sum(payments.values(), Decimal("0"))
    return _outcome(
        selected,
        payments,
        reason="vcg_externality",
        diagnostics={"budget_feasible": total <= case.budget, "total_payment": str(total)},
    )


def allocate_expanded(
    method_id: str,
    case: ProcurementInput,
    seed: int,
    params: Mapping[str, Any],
) -> MarketOutcome:
    if method_id == "bfm_vm":
        return allocate_bfm_vm(case)
    if method_id.startswith("triple_eagle_"):
        return allocate_triple_eagle(method_id, case, seed)
    if method_id.startswith("jt_"):
        return _jt_mechanism(method_id, case, seed, params)
    if method_id == "public_value_first":
        selected = _ordered_budget_selection(
            case,
            lambda seller: (-float(case.seller_values.get(seller, 0.0)), seller),
        )
        return _pay_as_bid(case, selected, method_id)
    if method_id == "value_cost_greedy":
        selected = _ordered_budget_selection(
            case,
            lambda seller: (
                -float(case.seller_values.get(seller, 0.0))
                / max(float(case.reported_costs[seller]), 1e-12),
                seller,
            ),
        )
        return _pay_as_bid(case, selected, method_id)
    if method_id == "reverse_first_price":
        return _reverse(case, second_price=False)
    if method_id == "reverse_second_price":
        return _reverse(case, second_price=True)
    if method_id == "uniform_posted_offer":
        return _posted(case, scaled=False)
    if method_id == "value_scaled_posted_offer":
        return _posted(case, scaled=True)
    if method_id == "generalized_proportional_share":
        return _proportional(case, half_budget=False)
    if method_id == "cgl_deterministic":
        return _cgl_deterministic(case)
    if method_id == "cgl_randomized":
        return _cgl_randomized(case, seed)
    if method_id == "procurement_vcg":
        return _vcg(case)
    raise KeyError(f"unknown expanded procurement method: {method_id}")


__all__ = ["allocate_expanded"]
