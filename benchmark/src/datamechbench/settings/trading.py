"""Repeated-distribution and structural trading settings."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from ..models import TradeCase, TradeInput


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(float(value), 6)))


def _trade_case(
    case_id: str,
    setting: str,
    values: list[float],
    costs: list[float],
    *,
    assumptions: tuple[str, ...],
    **metadata,
) -> TradeCase:
    buyers = tuple(f"b{index}" for index in range(len(values)))
    sellers = tuple(f"s{index}" for index in range(len(costs)))
    true_values = {buyer: _decimal(value) for buyer, value in zip(buyers, values, strict=True)}
    true_costs = {seller: _decimal(cost) for seller, cost in zip(sellers, costs, strict=True)}
    case_type = "single_sale" if len(sellers) == 1 else "double_auction"
    posted = _decimal(float(np.median(values))) if case_type == "single_sale" else None
    public = TradeInput(
        product_id=f"{case_id}-data-access",
        buyer_ids=buyers,
        seller_ids=sellers,
        bids=dict(true_values),
        asks=dict(true_costs),
        posted_price=posted,
        metadata={
            "benchmark_setting": setting,
            "prior_values": tuple(str(value) for value in true_values.values()),
            **metadata,
        },
    )
    return TradeCase(
        case_id=case_id,
        public=public,
        true_values=true_values,
        true_costs=true_costs,
        case_type=case_type,
        metadata={
            "benchmark_setting": setting,
            "assumptions": assumptions,
            "market_size": max(len(values), len(costs)),
            "pilot": False,
            **metadata,
        },
        attack_labels={actor: "truthful" for actor in (*buyers, *sellers)},
    )


def make_bilateral_trade_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    rng = np.random.default_rng(seed)
    regular = sorted(rng.uniform(0.0, 1.0, 10), reverse=True)
    beta = sorted(rng.beta(2.0, 5.0, 10), reverse=True)
    mixture = sorted(
        np.concatenate((rng.uniform(0.05, 0.25, 5), rng.uniform(0.75, 0.95, 5))),
        reverse=True,
    )
    assumptions = ("single_unit", "independent_private_values", "truthful_reports", "known_prior")
    return (
        _trade_case("TBIL-uniform", "T-BILATERAL", regular, [0.25], assumptions=assumptions, distribution="uniform_regular", reserve=0.25),
        _trade_case("TBIL-beta", "T-BILATERAL", beta, [0.20], assumptions=assumptions, distribution="beta_regular", reserve=0.20),
        _trade_case("TBIL-mixture", "T-BILATERAL", mixture, [0.45], assumptions=assumptions, distribution="irregular_mixture", reserve=0.45),
    )


def make_double_auction_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    rng = np.random.default_rng(seed)
    cases = []
    for size in (2, 5, 10):
        for overlap, shift in (("low", 0.55), ("medium", 0.25), ("high", 0.05)):
            values = sorted(rng.uniform(0.45, 1.0, size), reverse=True)
            costs = sorted(rng.uniform(0.0, 0.55, size) + shift)
            cases.append(
                _trade_case(
                    f"TDOUBLE-n{size}-{overlap}",
                    "T-DOUBLE",
                    list(values),
                    list(costs),
                    assumptions=("single_unit", "independent_private_values", "truthful_reports", "complete_true_types"),
                    overlap=overlap,
                    supply_demand="balanced",
                )
            )
    return tuple(cases)


def make_no_trade_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    del seed
    assumptions = ("single_unit", "independent_private_values", "truthful_reports", "complete_true_types")
    return (
        _trade_case("TNOTRADE-single", "T-NO-TRADE", [0.10, 0.20, 0.30], [0.80], assumptions=assumptions, overlap="none"),
        _trade_case("TNOTRADE-double", "T-NO-TRADE", [0.10, 0.15, 0.20, 0.25, 0.30], [0.70, 0.75, 0.80, 0.85, 0.90], assumptions=assumptions, overlap="none"),
    )


def make_correlated_trade_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    rng = np.random.default_rng(seed)
    cases = []
    for size in (2, 5, 10):
        common = rng.uniform(0.35, 0.65)
        values = sorted(common + rng.normal(0.20, 0.05, size), reverse=True)
        costs = sorted(common + rng.normal(-0.20, 0.05, size))
        cases.append(
            _trade_case(
                f"TCORR-n{size}",
                "T-CORRELATED",
                list(values),
                list(costs),
                assumptions=("single_unit", "correlated_private_values", "truthful_reports", "complete_true_types"),
                overlap="high",
                correlation_model="common_value_component",
            )
        )
    return tuple(cases)


def make_market_thickness_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    """Controlled double auctions varying both trade count and surplus margin."""

    del seed
    cases = []
    sizes = ((2, 1), (4, 3), (8, 6), (16, 12))

    def append_case(
        size: int,
        efficient_count: int,
        profile: str,
        values: list[float],
        costs: list[float],
    ) -> None:
        ordered_values = sorted(values, reverse=True)
        ordered_costs = sorted(costs)
        minimum_surplus = min(
            value - cost
            for value, cost in zip(
                ordered_values[:efficient_count],
                ordered_costs[:efficient_count],
                strict=True,
            )
        )
        suffix = "" if profile == "reference" else f"-{profile}"
        cases.append(
            _trade_case(
                f"TTHICK-n{size}-k{efficient_count}{suffix}",
                "T-MARKET-THICKNESS",
                values,
                costs,
                assumptions=(
                    "single_unit",
                    "independent_private_values",
                    "truthful_reports",
                    "complete_true_types",
                ),
                efficient_trade_count=efficient_count,
                thickness_axis="efficient_trade_count",
                surplus_margin_profile=profile,
                minimum_efficient_surplus=minimum_surplus,
                supply_demand="balanced",
                overlap="controlled_margin",
            )
        )

    for size, efficient_count in sizes:
        values = [1.0 - 0.01 * index for index in range(efficient_count)]
        values.extend(0.10 - 0.001 * index for index in range(size - efficient_count))
        costs = [0.20 + 0.01 * index for index in range(efficient_count)]
        costs.extend(0.90 + 0.001 * index for index in range(size - efficient_count))
        append_case(size, efficient_count, "reference", values, costs)

    for size, efficient_count in sizes:
        for profile, margin in (
            ("tight", 0.02),
            ("narrow", 0.15),
            ("wide", 0.45),
            ("very_wide", 0.90),
        ):
            values = [
                0.5 + margin / 2 + 0.0001 * (efficient_count - index)
                for index in range(efficient_count)
            ]
            values.extend(
                0.10 - 0.001 * index for index in range(size - efficient_count)
            )
            costs = [
                0.5 - margin / 2 + 0.0001 * index
                for index in range(efficient_count)
            ]
            costs.extend(
                0.90 + 0.001 * index for index in range(size - efficient_count)
            )
            append_case(size, efficient_count, profile, values, costs)
    return tuple(cases)


def make_market_geometry_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    """Hold market size and efficient volume fixed while changing support geometry.

    ``seed`` is accepted for the common setting-builder interface, but the
    frozen geometry cells are deterministic.  Mechanism randomness belongs to
    the study's separate seed panel.
    """

    del seed
    cases = []
    anchor = Decimal("0.5")
    assumptions = (
        "single_unit",
        "independent_private_values",
        "truthful_reports",
        "complete_true_types",
        "controlled_support_geometry",
    )
    asymmetry_labels = {
        Decimal("0.20"): "seller_margin_dominant",
        Decimal("0.50"): "balanced_margin",
        Decimal("0.80"): "buyer_margin_dominant",
    }
    for margin in (Decimal("0.02"), Decimal("0.20"), Decimal("0.60")):
        for buyer_share in (Decimal("0.20"), Decimal("0.50"), Decimal("0.80")):
            step = min(Decimal("0.002"), margin / Decimal("100"))
            marginal_bid = anchor + margin * buyer_share
            marginal_ask = anchor - margin * (Decimal("1") - buyer_share)
            efficient_values = [
                marginal_bid + step * (7 - index) for index in range(8)
            ]
            efficient_costs = [
                marginal_ask - step * (7 - index) for index in range(8)
            ]
            nontrading_values = [
                anchor - Decimal("0.151") - Decimal("0.002") * index
                for index in range(8)
            ]
            nontrading_costs = [
                anchor + Decimal("0.163") + Decimal("0.002") * index
                for index in range(8)
            ]
            margin_code = f"{int(margin * 100):03d}"
            share_code = f"{int(buyer_share * 100):02d}"
            cases.append(
                _trade_case(
                    f"TGEOM-m{margin_code}-s{share_code}",
                    "T-MARKET-GEOMETRY",
                    [float(value) for value in (*efficient_values, *nontrading_values)],
                    [float(cost) for cost in (*efficient_costs, *nontrading_costs)],
                    assumptions=assumptions,
                    efficient_trade_count=8,
                    market_size=16,
                    geometry_study_version="1.0",
                    minimum_efficient_surplus=float(margin),
                    buyer_margin_share=float(buyer_share),
                    support_asymmetry=asymmetry_labels[buyer_share],
                    crossing_price_anchor=float(anchor),
                    supply_demand="balanced",
                    overlap="controlled_geometry",
                    primary_metric_eligible=False,
                )
            )
    return tuple(cases)


__all__ = [
    "make_bilateral_trade_cases",
    "make_correlated_trade_cases",
    "make_double_auction_cases",
    "make_market_geometry_cases",
    "make_market_thickness_cases",
    "make_no_trade_cases",
]
