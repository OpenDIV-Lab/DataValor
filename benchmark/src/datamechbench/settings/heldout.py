"""Frozen held-out cases for the KDD confirmatory protocol."""

from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Mapping

from ..data import OwnerDataset
from ..heldout_sources import CalibratedTradeProfile
from ..models import ProcurementCase, ProcurementInput, TradeCase, TradeInput
from .valuation import _dataset_case, _replicate_owner_dataset

_VALUATION_BLOCKS = {
    "openml-44-spambase": "VHO-spambase",
    "openml-31-credit-g": "VHO-credit-g",
    "openml-1461-bank-marketing": "VHO-bank-marketing",
}


def make_heldout_valuation_cases(
    datasets: Mapping[str, OwnerDataset],
    *,
    independent_blocks: Mapping[str, str] | None = None,
) -> tuple:
    cases = []
    block_overrides = independent_blocks or {}
    for source_id, clean in datasets.items():
        block = block_overrides.get(source_id, _VALUATION_BLOCKS.get(source_id, source_id))
        baseline_id = f"{block}-c1"
        for factor in (1, 2, 4):
            dataset = clean if factor == 1 else _replicate_owner_dataset(clean, "o0", factor)
            cases.append(_dataset_case(
                f"{block}-c{factor}",
                dataset,
                "V-REPLICATION-ROBUSTNESS",
                assumptions=(
                    "frozen_heldout_source",
                    "fixed_train_validation_test_split",
                    "exact_row_replication",
                    "fixed_owner_identity",
                ),
                cohort="heldout",
                evidence_scope="real_trained_game",
                independent_block=block,
                source_id=source_id,
                replicated_owner="o0",
                replication_factor=factor,
                replication_baseline_case_id=baseline_id,
                replication_group_id=f"{block}-o0",
                replication_mode="full_owner_bundle",
                primary_metric_eligible=factor > 1,
            ))
    return tuple(cases)


def _exact_ml_optimum(
    dataset: OwnerDataset,
    costs: Mapping[str, Decimal],
    budget: Decimal,
) -> tuple[tuple[str, ...], float]:
    best: tuple[str, ...] = ()
    best_value = dataset.utility_for_owners(())
    owners = dataset.owner_ids
    for count in range(len(owners) + 1):
        for subset in itertools.combinations(owners, count):
            if sum((costs[owner] for owner in subset), Decimal("0")) > budget:
                continue
            value = dataset.utility_for_owners(subset)
            if value > best_value or (value == best_value and subset < best):
                best, best_value = subset, value
    return best, best_value


def make_heldout_procurement_cases(
    datasets: Mapping[str, OwnerDataset],
    calibrated_costs: Mapping[str, Mapping[str, Decimal | float]],
) -> tuple[ProcurementCase, ...]:
    cases: list[ProcurementCase] = []
    if len(datasets) != len(calibrated_costs):
        raise ValueError("procurement confirmation requires one cost cohort per dataset block")
    for (source_id, dataset), (block, raw_costs) in zip(
        datasets.items(), calibrated_costs.items(), strict=True
    ):
        costs = {owner: Decimal(str(raw_costs[owner])) for owner in dataset.owner_ids}
        empty = dataset.utility_for_owners(())
        seller_values = {
            owner: max(0.0, dataset.utility_for_owners((owner,)) - empty)
            for owner in dataset.owner_ids
        }
        total_cost = sum(costs.values(), Decimal("0"))
        for ratio in (0.3, 0.5):
            budget = total_cost * Decimal(str(ratio))
            optimum, optimum_value = _exact_ml_optimum(dataset, costs, budget)
            largest_share = max(seller_values.values()) / optimum_value if optimum_value else 0.0
            public = ProcurementInput(
                seller_ids=dataset.owner_ids,
                reported_costs=dict(costs),
                budget=budget,
                utility=dataset.utility_for_owners,
                seller_values=seller_values,
                metadata={
                    "mechanism_utility": "heldout_validation_proxy",
                    "cost_calibration": "ChileCompra",
                    "source_dataset": source_id,
                    "difficulty_axis": "largest_singleton_share",
                },
            )
            cases.append(ProcurementCase(
                case_id=f"{block}-b{int(ratio * 100)}",
                public=public,
                true_costs=dict(costs),
                case_type="real_owner_data",
                metadata={
                    "benchmark_setting": "P-MARKET-CONCENTRATION",
                    "cohort": "heldout",
                    "evidence_scope": "real_trained_game",
                    "independent_block": block,
                    "source_dataset": source_id,
                    "budget_ratio": ratio,
                    "largest_singleton_share": largest_share,
                    "exact_optimum": optimum,
                    "exact_opt_utility": optimum_value,
                    "owner_dataset": dataset,
                    "pilot": False,
                    "assumptions": (
                        "open_data_backed_utility",
                        "market_calibrated_cost_proxy",
                        "single_parameter_sellers",
                        "truthful_reports",
                    ),
                },
                attack_labels={owner: "truthful" for owner in dataset.owner_ids},
            ))
    return tuple(cases)


def make_heldout_trading_cases(
    profiles: Mapping[str, CalibratedTradeProfile],
    *,
    independent_blocks: Mapping[str, str] | None = None,
) -> tuple[TradeCase, ...]:
    cases: list[TradeCase] = []
    block_lookup = dict(independent_blocks or {})
    for case_id, profile in profiles.items():
        block = block_lookup.get(case_id, case_id)
        buyers = tuple(f"b{index}" for index in range(len(profile.buyer_values)))
        sellers = tuple(f"s{index}" for index in range(len(profile.seller_costs)))
        values = {
            buyer: Decimal(str(round(profile.buyer_values[index], 9)))
            for index, buyer in enumerate(buyers)
        }
        costs = {
            seller: Decimal(str(round(profile.seller_costs[index], 9)))
            for index, seller in enumerate(sellers)
        }
        efficient_count = sum(
            value >= cost
            for value, cost in zip(
                sorted(values.values(), reverse=True), sorted(costs.values()), strict=True
            )
        )
        public = TradeInput(
            product_id=f"{case_id}-data-access",
            buyer_ids=buyers,
            seller_ids=sellers,
            bids=dict(values),
            asks=dict(costs),
            metadata={
                "source_market": "Elexon BOD",
                "benchmark_setting": "T-MARKET-THICKNESS",
            },
        )
        cases.append(TradeCase(
            case_id=case_id,
            public=public,
            true_values=values,
            true_costs=costs,
            case_type="double_auction",
            metadata={
                "benchmark_setting": "T-MARKET-THICKNESS",
                "cohort": "heldout",
                "evidence_scope": "real_trained_game",
                "independent_block": block,
                "market_size": len(buyers),
                "efficient_trade_count": efficient_count,
                "thickness_axis": "efficient_trade_count",
                "source_row_count": profile.source_row_count,
                "pilot": False,
                "assumptions": (
                    "single_unit",
                    "market_calibrated_type_proxy",
                    "truthful_reports",
                    "complete_true_types",
                ),
            },
            attack_labels={actor: "truthful" for actor in (*buyers, *sellers)},
        ))
    return tuple(cases)


__all__ = [
    "make_heldout_procurement_cases",
    "make_heldout_trading_cases",
    "make_heldout_valuation_cases",
]
