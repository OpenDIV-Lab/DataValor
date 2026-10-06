"""Focused procurement settings for budget-feasible mechanism comparisons."""

from __future__ import annotations

import itertools
from dataclasses import replace
from decimal import Decimal

import numpy as np

from ..data import make_procurement_cases, make_real_valuation_cases
from ..models import ProcurementCase, ProcurementInput


def _exact_additive_opt(
    sellers: tuple[str, ...], values: dict[str, float], costs: dict[str, Decimal], budget: Decimal
) -> tuple[tuple[str, ...], float]:
    best: tuple[str, ...] = ()
    best_value = 0.0
    for count in range(len(sellers) + 1):
        for subset in itertools.combinations(sellers, count):
            if sum((costs[item] for item in subset), Decimal("0")) > budget:
                continue
            value = sum(values[item] for item in subset)
            if value > best_value or (value == best_value and subset < best):
                best, best_value = subset, value
    return best, best_value


def make_procurement_additive_cases(seed: int = 42) -> tuple[ProcurementCase, ...]:
    rng = np.random.default_rng(seed)
    sellers = tuple(f"p{index}" for index in range(10))
    values = {
        seller: float(value)
        for seller, value in zip(sellers, np.linspace(2.0, 20.0, len(sellers)), strict=True)
    }
    independent_draws = rng.uniform(2.0, 12.0, len(sellers))
    profiles = {
        "independent": {
            seller: Decimal(str(round(float(cost), 6)))
            for seller, cost in zip(sellers, independent_draws, strict=True)
        },
        "positive": {
            seller: Decimal(str(round(1.0 + values[seller] * 0.55, 6))) for seller in sellers
        },
        "negative": {
            seller: Decimal(str(round(13.0 - values[seller] * 0.45, 6))) for seller in sellers
        },
    }
    cases: list[ProcurementCase] = []
    for correlation, costs in profiles.items():
        for ratio in (0.3, 0.6):
            local_values = dict(values)
            dominant = correlation == "independent" and ratio == 0.6
            if dominant:
                local_values[sellers[-1]] = sum(values.values()) * 0.8
            budget = sum(costs.values(), Decimal("0")) * Decimal(str(ratio))

            def utility(selected, local_values=local_values):
                return float(sum(local_values[item] for item in set(selected)))

            optimum, optimum_value = _exact_additive_opt(
                sellers, local_values, costs, budget
            )
            public = ProcurementInput(
                seller_ids=sellers,
                reported_costs=dict(costs),
                budget=budget,
                utility=utility,
                seller_values=local_values,
                metadata={
                    "utility_class": "additive_public_values",
                    "mechanism_utility": "public_additive_values",
                },
            )
            cases.append(
                ProcurementCase(
                    case_id=f"PADD-{correlation}-b{int(ratio * 100)}",
                    public=public,
                    true_costs=dict(costs),
                    case_type="analytic",
                    metadata={
                        "benchmark_setting": "P-ADDITIVE",
                        "assumptions": (
                            "additive_public_values",
                            "indivisible_single_parameter_sellers",
                            "truthful_reports",
                            "exact_optimum_available",
                        ),
                        "budget_ratio": ratio,
                        "cost_value_correlation": correlation,
                        "dominant_singleton": dominant,
                        "exact_optimum": optimum,
                        "exact_opt_utility": optimum_value,
                        "pilot": False,
                    },
                    attack_labels={seller: "truthful" for seller in sellers},
                )
            )
    return tuple(cases)


def make_procurement_submodular_cases(seed: int = 42) -> tuple[ProcurementCase, ...]:
    source = [case for case in make_procurement_cases(seed=seed) if case.case_type == "submodular"]
    return tuple(
        replace(
            case,
            case_id=case.case_id.replace("P-C-coverage", "PSMOD-coverage"),
            public=replace(
                case.public,
                metadata={
                    **case.public.metadata,
                    "mechanism_utility": "public_weighted_coverage",
                },
            ),
            metadata={
                **case.metadata,
                "benchmark_setting": "P-SUBMODULAR",
                "pilot": False,
                "assumptions": (
                    "monotone_submodular_utility",
                    "single_parameter_sellers",
                    "truthful_reports",
                    "exact_optimum_available",
                ),
            },
        )
        for case in source
    )


def make_procurement_ml_cases(seed: int = 42) -> tuple[ProcurementCase, ...]:
    valuation = make_real_valuation_cases(seed)
    source = [
        case
        for case in make_procurement_cases(valuation, seed=seed)
        if case.case_type == "real_owner_data" and case.metadata.get("source_case_id") == "C-real-clean"
    ]
    return tuple(
        replace(
            case,
            case_id=case.case_id.replace("P-C-real-clean", "PML-clean"),
            public=replace(
                case.public,
                metadata={
                    **case.public.metadata,
                    "mechanism_utility": "validation_proxy",
                    "seller_information": "owner_id_cost_and_public_proxy_value",
                },
            ),
            metadata={
                **case.metadata,
                "benchmark_setting": "P-ML-ACQUISITION",
                "assumptions": (
                    "fixed_train_validation_test_split",
                    "seller_data_hidden_from_mechanism",
                    "truthful_reports",
                ),
                "evaluator_utility": "held_out_test",
            },
        )
        for case in source
    )


def make_procurement_concentration_cases(seed: int = 42) -> tuple[ProcurementCase, ...]:
    """Finite singleton-concentration axis for budget-feasible mechanisms."""

    del seed
    sellers = tuple(f"m{index}" for index in range(8))
    costs = {seller: Decimal("1") for seller in sellers}
    profiles = {
        "diffuse": 1.0,
        "low": 2.0,
        "moderate": 4.0,
        "high": 8.0,
        "dominant": 12.0,
    }
    cases: list[ProcurementCase] = []
    for level, leading_value in profiles.items():
        values = {seller: 1.0 for seller in sellers}
        values[sellers[0]] = leading_value
        for budget_count in (2, 3, 4, 5):
            budget = Decimal(budget_count)

            def utility(selected, values=values):
                return float(sum(values[item] for item in set(selected)))

            optimum, optimum_value = _exact_additive_opt(sellers, values, costs, budget)
            largest_share = max(values.values()) / optimum_value
            public = ProcurementInput(
                seller_ids=sellers,
                reported_costs=dict(costs),
                budget=budget,
                utility=utility,
                seller_values=dict(values),
                metadata={
                    "utility_class": "additive_public_values",
                    "mechanism_utility": "public_additive_values",
                    "difficulty_axis": "largest_singleton_share",
                },
            )
            cases.append(
                ProcurementCase(
                    case_id=f"PCONC-{level}-b{budget_count}",
                    public=public,
                    true_costs=dict(costs),
                    case_type="analytic",
                    metadata={
                        "benchmark_setting": "P-MARKET-CONCENTRATION",
                        "assumptions": (
                            "monotone_submodular_utility",
                            "additive_public_values",
                            "single_parameter_sellers",
                            "truthful_reports",
                            "exact_optimum_available",
                        ),
                        "concentration_level": level,
                        "largest_singleton_share": largest_share,
                        "exact_optimum": optimum,
                        "exact_opt_utility": optimum_value,
                        "budget_item_count": budget_count,
                        "pilot": False,
                    },
                    attack_labels={seller: "truthful" for seller in sellers},
                )
            )
    return tuple(cases)


__all__ = [
    "make_procurement_additive_cases",
    "make_procurement_concentration_cases",
    "make_procurement_ml_cases",
    "make_procurement_submodular_cases",
]
