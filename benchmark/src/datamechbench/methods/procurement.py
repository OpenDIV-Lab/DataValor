"""P-track adapters for indivisible data-owner bundles."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    Ask,
    BudgetAwareProcurement,
    Money,
    PricingRequest,
    ProportionalShareProcurement,
)

from ..models import (
    AllocationRecord,
    MarketOutcome,
    MethodSpec,
    PaymentRecord,
    ProcurementInput,
)
from ..registry import MethodRegistry
from .procurement_truthful import allocate_expanded


def _spec(
    method_id: str,
    role: str,
    source: str,
    capabilities: set[str],
    assumptions: tuple[str, ...] = (),
    *,
    family_id: str | None = None,
    stochastic: bool = False,
    case_types: frozenset[str] = frozenset({"analytic", "submodular", "real_owner_data"}),
) -> MethodSpec:
    return MethodSpec(
        method_id=method_id,
        family_id=family_id or method_id,
        track="procurement",
        role=role,
        source=source,
        version="1.0",
        stochastic=stochastic,
        capabilities=frozenset(capabilities),
        assumptions=assumptions,
        supported_case_types=case_types,
    )


def _pricing_request(case: ProcurementInput, sellers: tuple[str, ...] | None = None) -> PricingRequest:
    included = sellers if sellers is not None else case.seller_ids
    products = tuple(
        DataProduct(
            seller,
            f"owner bundle {seller}",
            DataReference(f"benchmark://bundle/{seller}", "owner_bundle"),
            seller,
        )
        for seller in included
    )
    asks = tuple(
        Ask(
            f"ask-{seller}",
            seller,
            (seller,),
            Money(case.reported_costs[seller]),
            Decimal("1"),
        )
        for seller in included
    )
    return PricingRequest(
        products,
        asks=asks,
        market_context={
            "budget": str(case.budget),
            "buyer_id": "buyer",
            "seller_values": {seller: case.seller_values[seller] for seller in included},
        },
    )


def _normalized_outcome(pricing_outcome, *, require_full_quantity: bool = False) -> MarketOutcome:
    selected: list[str] = []
    payments: list[PaymentRecord] = []
    allocations: list[AllocationRecord] = []
    for allocation, payment in zip(pricing_outcome.allocations, pricing_outcome.payments, strict=True):
        quantity = allocation.quantity
        if require_full_quantity and quantity < Decimal("1"):
            continue
        seller = payment.payee_id
        selected.append(seller)
        allocations.append(AllocationRecord(seller, "buyer", payment.product_ids, quantity))
        payments.append(
            PaymentRecord(
                payment.payer_id,
                seller,
                payment.amount.amount,
                payment.reason,
                payment.product_ids,
            )
        )
    return MarketOutcome(
        selected_ids=tuple(selected),
        allocations=tuple(allocations),
        payments=tuple(payments),
        diagnostics=dict(pricing_outcome.diagnostics),
    )


@dataclass
class _ProcurementAdapter:
    spec: MethodSpec
    params: Mapping[str, Any]

    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        raise NotImplementedError


class _CheapestFirst(_ProcurementAdapter):
    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        del seed
        priced = BudgetAwareProcurement().price(_pricing_request(case), RunContext("benchmark"))
        return _normalized_outcome(priced, require_full_quantity=True)


def _ask_payment(seller: str, amount: Decimal) -> PaymentRecord:
    return PaymentRecord("buyer", seller, amount, "reported_cost", (seller,))


class _MarginalUtilityPerCost(_ProcurementAdapter):
    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        del seed
        selected: list[str] = []
        remaining = case.budget
        calls = 0
        current_utility = float(case.utility(()))
        calls += 1
        while True:
            candidates = []
            for seller in case.seller_ids:
                cost = case.reported_costs[seller]
                if seller in selected or cost <= 0 or cost > remaining:
                    continue
                utility = float(case.utility(tuple((*selected, seller))))
                calls += 1
                marginal = utility - current_utility
                candidates.append((marginal / float(cost), marginal, seller, utility))
            if not candidates:
                break
            ratio, marginal, seller, new_utility = min(
                candidates,
                key=lambda item: (-item[0], -item[1], item[2]),
            )
            if ratio <= 0:
                break
            selected.append(seller)
            remaining -= case.reported_costs[seller]
            current_utility = new_utility
        return MarketOutcome(
            selected_ids=tuple(selected),
            allocations=tuple(AllocationRecord(seller, "buyer", (seller,)) for seller in selected),
            payments=tuple(_ask_payment(seller, case.reported_costs[seller]) for seller in selected),
            diagnostics={"utility_calls": calls, "remaining_budget": str(remaining)},
        )


class _BudgetOptimum(_ProcurementAdapter):
    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        del seed
        best_ids: tuple[str, ...] = ()
        best_utility = float("-inf")
        best_cost = Decimal("Infinity")
        calls = 0
        for count in range(len(case.seller_ids) + 1):
            for subset in itertools.combinations(case.seller_ids, count):
                cost = sum((case.reported_costs[seller] for seller in subset), Decimal("0"))
                if cost > case.budget:
                    continue
                utility = float(case.utility(subset))
                calls += 1
                if (
                    utility > best_utility
                    or (utility == best_utility and cost < best_cost)
                    or (utility == best_utility and cost == best_cost and subset < best_ids)
                ):
                    best_ids, best_utility, best_cost = subset, utility, cost
        return MarketOutcome(
            selected_ids=best_ids,
            allocations=tuple(AllocationRecord(seller, "buyer", (seller,)) for seller in best_ids),
            diagnostics={
                "utility_calls": calls,
                "reported_cost": str(best_cost),
                "allocation_utility": best_utility,
                "payment_semantics": "not_applicable_allocation_oracle",
            },
        )


class _ProportionalShare(_ProcurementAdapter):
    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        del seed
        positive = tuple(
            seller for seller in case.seller_ids if float(case.seller_values.get(seller, 0.0)) > 0
        )
        if not positive:
            return MarketOutcome(diagnostics={"assumption": "additive_public_values"})
        priced = ProportionalShareProcurement().price(
            _pricing_request(case, positive), RunContext("benchmark")
        )
        return _normalized_outcome(priced)


class _ExpandedProcurement(_ProcurementAdapter):
    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome:
        return allocate_expanded(self.spec.method_id, case, seed, self.params)


def register_procurement_methods(registry: MethodRegistry) -> None:
    entries = (
        (
            _spec("cheapest_first", "baseline", "DataValor", {"allocations", "payments"}),
            _CheapestFirst,
        ),
        (
            _spec(
                "marginal_utility_per_cost",
                "baseline",
                "benchmark",
                {"allocations", "payments"},
            ),
            _MarginalUtilityPerCost,
        ),
        (
            _spec("budget_optimum", "oracle", "benchmark", {"allocations"}),
            _BudgetOptimum,
        ),
        (
            _spec(
                "proportional_share",
                "method",
                "Singer proportional-share procurement",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("additive_public_values", "indivisible_single_parameter_sellers"),
            ),
            _ProportionalShare,
        ),
        (
            _spec("public_value_first", "baseline", "benchmark", {"allocations", "payments"}),
            _ExpandedProcurement,
        ),
        (
            _spec("value_cost_greedy", "baseline", "benchmark", {"allocations", "payments"}),
            _ExpandedProcurement,
        ),
        (
            _spec("reverse_first_price", "baseline", "benchmark", {"allocations", "payments"}),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "reverse_second_price",
                "method",
                "Vickrey procurement",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "uniform_posted_offer",
                "method",
                "posted-price procurement",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "value_scaled_posted_offer",
                "method",
                "posted-price procurement",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "generalized_proportional_share",
                "method",
                "Singer 2010",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "cgl_deterministic",
                "method",
                "Chen-Gravin-Lu 2011 GREEDY-SUBMODULAR core",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "cgl_randomized",
                "method",
                "Chen-Gravin-Lu 2011 universally-truthful mixture",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
                stochastic=True,
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "procurement_vcg",
                "method",
                "VCG budget-relaxed reference",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("budget_relaxed",),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "jt_greedy_tm",
                "method",
                "Jalaly & Tardos 2018 Greedy-TM(0.5)",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "jt_random_tm",
                "method",
                "Jalaly & Tardos 2018 Random-TM(0.5)",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
                stochastic=True,
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "jt_random_eom",
                "method",
                "Jalaly & Tardos 2018 Random-EOM(0.5)",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers", "exact_optimum_oracle"),
                stochastic=True,
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "jt_deterministic_eom",
                "method",
                "Jalaly & Tardos 2018 Deterministic-EOM",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers", "exact_optimum_oracle"),
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "bfm_vm",
                "method",
                "Cui et al. 2026 BFM-VM",
                {
                    "allocations",
                    "payments",
                    "truthful_payments",
                    "strategic_reports",
                },
                assumptions=(
                    "nonnegative_normalized_submodular_utility",
                    "single_parameter_sellers",
                ),
                case_types=frozenset(
                    {"analytic", "submodular", "real_owner_data"}
                ),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "triple_eagle_randomized",
                "method",
                "Han et al. 2023 TripleEagleRan",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
                family_id="triple_eagle",
                stochastic=True,
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
        (
            _spec(
                "triple_eagle_deterministic",
                "method",
                "Han et al. 2023 TripleEagleDet",
                {"allocations", "payments", "truthful_payments", "strategic_reports"},
                assumptions=("monotone_submodular_utility", "single_parameter_sellers"),
                family_id="triple_eagle",
                case_types=frozenset({"analytic", "submodular", "real_owner_data"}),
            ),
            _ExpandedProcurement,
        ),
    )
    for spec, adapter in entries:
        registry.register(spec, lambda params, spec=spec, adapter=adapter: adapter(spec, params))


__all__ = ["register_procurement_methods"]
