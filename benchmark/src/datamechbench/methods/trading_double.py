"""Native single-sale and homogeneous double-auction benchmark rules."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import numpy as np

from ..models import AllocationRecord, MarketOutcome, PaymentRecord, TradeInput


def _ranked(case: TradeInput):
    buyers = sorted(case.buyer_ids, key=lambda buyer: (-case.bids[buyer], buyer))
    sellers = sorted(case.seller_ids, key=lambda seller: (case.asks[seller], seller))
    count = 0
    for buyer, seller in zip(buyers, sellers):
        if case.bids[buyer] < case.asks[seller]:
            break
        count += 1
    return buyers, sellers, count


def _market_outcome(
    case: TradeInput,
    pairs: list[tuple[str, str]],
    payments: list[PaymentRecord],
    diagnostics: Mapping[str, Any],
) -> MarketOutcome:
    selected = tuple(actor for pair in pairs for actor in pair)
    return MarketOutcome(
        selected_ids=selected,
        allocations=tuple(
            AllocationRecord(buyer, seller, (case.product_id,)) for buyer, seller in pairs
        ),
        payments=tuple(payments),
        diagnostics=dict(diagnostics),
    )


def _direct_uniform(
    case: TradeInput,
    pairs: list[tuple[str, str]],
    price: Decimal,
    reason: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> MarketOutcome:
    payments = [
        PaymentRecord(buyer, seller, price, reason, (case.product_id,))
        for buyer, seller in pairs
    ]
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "trade_count": len(pairs),
            "uniform_price": price,
            "auctioneer_surplus": Decimal("0"),
            "weak_budget_balance": True,
            "strong_budget_balance": True,
            **dict(diagnostics or {}),
        },
    )


def clear_single(
    method_id: str,
    case: TradeInput,
    seed: int,
    params: Mapping[str, Any],
) -> MarketOutcome:
    del seed, params
    bids = sorted(case.buyer_ids, key=lambda buyer: (-case.bids[buyer], buyer))
    if not bids or not case.seller_ids:
        return MarketOutcome()
    seller = case.seller_ids[0]
    reserve = case.asks[seller]
    winner = bids[0]
    second = case.bids[bids[1]] if len(bids) > 1 else Decimal("0")
    if method_id == "myerson_reserve":
        prior = tuple(Decimal(str(value)) for value in case.metadata.get("prior_values", ()))
        if prior:
            monopoly = min(
                prior,
                key=lambda candidate: (
                    -candidate
                    * sum(value >= candidate for value in prior)
                    / Decimal(len(prior)),
                    candidate,
                ),
            )
            reserve = max(reserve, monopoly)
        elif case.posted_price is not None:
            reserve = max(reserve, case.posted_price)
    if case.bids[winner] < reserve:
        return MarketOutcome(diagnostics={"reserve": reserve, "accepted": False})
    if method_id in {"second_price", "second_price_reserve", "myerson_reserve", "english_auction"}:
        price = max(reserve, second)
    elif method_id in {"first_price", "dutch_auction"}:
        price = case.bids[winner]
    elif method_id == "all_pay":
        payments = [
            PaymentRecord(buyer, seller, case.bids[buyer], "all_pay", (case.product_id,))
            for buyer in bids
        ]
        return _market_outcome(
            case,
            [(winner, seller)],
            payments,
            {"trade_count": 1, "all_pay": True, "seller_revenue": sum(case.bids.values())},
        )
    elif method_id == "efficient_single_sale":
        return _market_outcome(
            case,
            [(winner, seller)],
            [],
            {"trade_count": 1, "payment_semantics": "not_applicable_allocation_oracle"},
        )
    else:
        raise KeyError(f"unknown single-sale method: {method_id}")
    return _direct_uniform(
        case,
        [(winner, seller)],
        price,
        method_id,
        {"reserve": reserve},
    )


def _k_double(case: TradeInput, method_id: str) -> MarketOutcome:
    buyers, sellers, count = _ranked(case)
    if count == 0:
        return MarketOutcome()
    marginal_bid = case.bids[buyers[count - 1]]
    marginal_ask = case.asks[sellers[count - 1]]
    if method_id == "seller_price_double":
        price = marginal_ask
    elif method_id == "buyer_price_double":
        price = marginal_bid
    else:
        price = (marginal_bid + marginal_ask) / Decimal("2")
    return _direct_uniform(
        case,
        list(zip(buyers[:count], sellers[:count], strict=True)),
        price,
        method_id,
    )


def _pay_as_bid(case: TradeInput) -> MarketOutcome:
    buyers, sellers, count = _ranked(case)
    pairs = list(zip(buyers[:count], sellers[:count], strict=True))
    payments: list[PaymentRecord] = []
    surplus = Decimal("0")
    for buyer, seller in pairs:
        bid = case.bids[buyer]
        ask = case.asks[seller]
        payments.extend(
            (
                PaymentRecord(buyer, "platform", bid, "pay_as_bid_buyer", (case.product_id,)),
                PaymentRecord("platform", seller, ask, "pay_as_bid_seller", (case.product_id,)),
            )
        )
        surplus += bid - ask
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "trade_count": count,
            "auctioneer_surplus": surplus,
            "weak_budget_balance": True,
            "strong_budget_balance": surplus == 0,
        },
    )


def _trade_reduction(case: TradeInput) -> MarketOutcome:
    buyers, sellers, efficient = _ranked(case)
    count = max(0, efficient - 1)
    buyer_price = case.bids[buyers[efficient - 1]] if efficient else None
    seller_price = case.asks[sellers[efficient - 1]] if efficient else None
    if count == 0:
        return MarketOutcome(
            diagnostics={
                "allocation_rule": "mcafee_trade_reduction",
                "trade_count": 0,
                "efficient_trade_count": efficient,
                "buyer_price": str(buyer_price) if buyer_price is not None else None,
                "seller_price": str(seller_price) if seller_price is not None else None,
                "auctioneer_surplus": Decimal("0"),
                "weak_budget_balance": True,
                "strong_budget_balance": True,
            }
        )
    assert buyer_price is not None and seller_price is not None
    pairs = list(zip(buyers[:count], sellers[:count], strict=True))
    payments: list[PaymentRecord] = []
    for buyer, seller in pairs:
        payments.extend(
            (
                PaymentRecord(buyer, "platform", buyer_price, "trade_reduction_buyer", (case.product_id,)),
                PaymentRecord("platform", seller, seller_price, "trade_reduction_seller", (case.product_id,)),
            )
        )
    surplus = (buyer_price - seller_price) * count
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "allocation_rule": "mcafee_trade_reduction",
            "trade_count": count,
            "efficient_trade_count": efficient,
            "buyer_price": str(buyer_price),
            "seller_price": str(seller_price),
            "auctioneer_surplus": surplus,
            "weak_budget_balance": surplus >= 0,
            "strong_budget_balance": surplus == 0,
        },
    )


def _vcg(case: TradeInput) -> MarketOutcome:
    buyers, sellers, count = _ranked(case)
    if count == 0:
        return MarketOutcome()
    next_bid = case.bids[buyers[count]] if count < len(buyers) else Decimal("0")
    next_ask = case.asks[sellers[count]] if count < len(sellers) else case.bids[buyers[count - 1]]
    buyer_price = max(case.asks[sellers[count - 1]], next_bid)
    seller_price = min(case.bids[buyers[count - 1]], next_ask)
    pairs = list(zip(buyers[:count], sellers[:count], strict=True))
    payments: list[PaymentRecord] = []
    for buyer, seller in pairs:
        payments.extend(
            (
                PaymentRecord(buyer, "platform", buyer_price, "vcg_buyer", (case.product_id,)),
                PaymentRecord("platform", seller, seller_price, "vcg_seller", (case.product_id,)),
            )
        )
    surplus = (buyer_price - seller_price) * count
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "trade_count": count,
            "buyer_price": buyer_price,
            "seller_price": seller_price,
            "auctioneer_surplus": surplus,
            "weak_budget_balance": surplus >= 0,
            "strong_budget_balance": surplus == 0,
        },
    )


def _sbba(case: TradeInput, seed: int) -> MarketOutcome:
    buyers, sellers, count = _ranked(case)
    if count == 0:
        return MarketOutcome(
            diagnostics={
                "branch": "no_trade",
                "efficient_trade_count": 0,
                "trade_count": 0,
                "weak_budget_balance": True,
                "strong_budget_balance": True,
            }
        )
    marginal_bid = case.bids[buyers[count - 1]]
    next_ask = case.asks[sellers[count]] if count < len(sellers) else Decimal("Infinity")
    if next_ask <= marginal_bid:
        # SBBA Case 1: s_(k+1) sets the price but is not a trading seller.
        price = next_ask
        trading_buyers = buyers[:count]
        chosen = sellers[:count]
        branch = "full_trade"
        excluded_seller = None
    else:
        # SBBA Case 2: b_k sets the price, b_k is excluded, and one of the k
        # efficient sellers is excluded uniformly at random (paper Section 3).
        price = marginal_bid
        efficient_sellers = sellers[:count]
        excluded_index = int(np.random.default_rng(seed).integers(count))
        excluded_seller = efficient_sellers[excluded_index]
        chosen = [
            seller for index, seller in enumerate(efficient_sellers)
            if index != excluded_index
        ]
        trading_buyers = buyers[: max(0, count - 1)]
        branch = "seller_lottery_trade_reduction"
    pairs = list(zip(trading_buyers, chosen, strict=True))
    return _direct_uniform(
        case,
        pairs,
        price,
        "sbba",
        {
            "branch": branch,
            "efficient_trade_count": count,
            "randomized_seller_exclusion": excluded_seller is not None,
            "excluded_seller": excluded_seller,
            "price_setter": "s_k_plus_1" if branch == "full_trade" else "b_k",
        },
    )


def _bilateral(case: TradeInput) -> MarketOutcome:
    buyers, sellers, count = _ranked(case)
    if count == 0:
        return MarketOutcome()
    price = (case.bids[buyers[0]] + case.asks[sellers[0]]) / Decimal("2")
    return _direct_uniform(case, [(buyers[0], sellers[0])], price, "bilateral_midpoint")


def _sample_price(case: TradeInput, buyers: list[str], sellers: list[str]) -> Decimal | None:
    ranked_buyers = sorted(buyers, key=lambda buyer: (-case.bids[buyer], buyer))
    ranked_sellers = sorted(sellers, key=lambda seller: (case.asks[seller], seller))
    profitable = [
        (buyer, seller)
        for buyer, seller in zip(ranked_buyers, ranked_sellers)
        if case.bids[buyer] >= case.asks[seller]
    ]
    if not profitable:
        return None
    buyer, seller = profitable[-1]
    return (case.bids[buyer] + case.asks[seller]) / Decimal("2")


def _random_sampling(
    case: TradeInput, seed: int, *, rationing: str = "priority"
) -> MarketOutcome:
    rng = np.random.default_rng(seed)
    left_buyers = [buyer for buyer in case.buyer_ids if rng.random() < 0.5]
    left_sellers = [seller for seller in case.seller_ids if rng.random() < 0.5]
    right_buyers = [buyer for buyer in case.buyer_ids if buyer not in left_buyers]
    right_sellers = [seller for seller in case.seller_ids if seller not in left_sellers]
    left_price = _sample_price(case, left_buyers, left_sellers)
    right_price = _sample_price(case, right_buyers, right_sellers)
    pairs: list[tuple[str, str]] = []
    priced_pairs: list[tuple[str, str, Decimal]] = []
    for buyers, sellers, price in (
        (left_buyers, left_sellers, right_price),
        (right_buyers, right_sellers, left_price),
    ):
        if price is None:
            continue
        willing_buyers = sorted(
            (buyer for buyer in buyers if case.bids[buyer] >= price),
            key=lambda buyer: (-case.bids[buyer], buyer),
        )
        willing_sellers = sorted(
            (seller for seller in sellers if case.asks[seller] <= price),
            key=lambda seller: (case.asks[seller], seller),
        )
        if rationing == "lottery":
            rng.shuffle(willing_buyers)
            rng.shuffle(willing_sellers)
        for buyer, seller in zip(willing_buyers, willing_sellers):
            pairs.append((buyer, seller))
            priced_pairs.append((buyer, seller, price))
    payments = [
        PaymentRecord(buyer, seller, price, "random_sampling_price", (case.product_id,))
        for buyer, seller, price in priced_pairs
    ]
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "trade_count": len(pairs),
            "auctioneer_surplus": Decimal("0"),
            "weak_budget_balance": True,
            "strong_budget_balance": True,
            "left_price": left_price,
            "right_price": right_price,
            "left_buyers": left_buyers,
            "left_sellers": left_sellers,
            "right_buyers": right_buyers,
            "right_sellers": right_sellers,
            "rationing": rationing,
        },
    )


def _equilibrium_price(
    case: TradeInput,
    buyers: list[str],
    sellers: list[str],
) -> Decimal | None:
    """Return a deterministic Walrasian price for a sampled unit market.

    Demand and supply follow MUDA's generic-value convention: a buyer is
    willing only above the price and a seller only below it.  Midpoints of
    adjacent reports represent every open interval on which both quantities
    are constant; report values cover the zero-width tie boundaries.
    """

    reports = sorted(
        {case.bids[buyer] for buyer in buyers}
        | {case.asks[seller] for seller in sellers}
    )
    if not reports:
        return None
    candidates = set(reports)
    candidates.update(
        (lower + upper) / Decimal("2")
        for lower, upper in zip(reports, reports[1:])
    )
    scale = max(Decimal("1"), *(abs(value) for value in reports))
    candidates.add(min(Decimal("0"), reports[0] - scale))
    candidates.add(reports[-1] + scale)

    equilibria: list[tuple[int, Decimal, Decimal]] = []
    for price in candidates:
        demand = sum(case.bids[buyer] > price for buyer in buyers)
        supply = sum(case.asks[seller] < price for seller in sellers)
        if demand != supply:
            continue
        clearance = min(abs(report - price) for report in reports)
        equilibria.append((demand, clearance, price))
    if not equilibria:  # Defensive: finite unit markets always have one.
        return None
    return max(equilibria, key=lambda item: (item[0], item[1], -item[2]))[2]


def _muda_submarket(
    case: TradeInput,
    buyers: list[str],
    sellers: list[str],
    cross_price: Decimal | None,
    *,
    rationing: str,
    rng: np.random.Generator,
) -> tuple[list[tuple[str, str]], list[PaymentRecord], Decimal, str]:
    if cross_price is None:
        return [], [], Decimal("0"), "no_cross_price"
    willing_buyers = sorted(
        (buyer for buyer in buyers if case.bids[buyer] > cross_price),
        key=lambda buyer: (-case.bids[buyer], buyer),
    )
    willing_sellers = sorted(
        (seller for seller in sellers if case.asks[seller] < cross_price),
        key=lambda seller: (case.asks[seller], seller),
    )
    quantity = min(len(willing_buyers), len(willing_sellers))
    if quantity == 0:
        return [], [], Decimal("0"), "no_trade"

    surplus = Decimal("0")
    if rationing == "lottery":
        if len(willing_buyers) > len(willing_sellers):
            rng.shuffle(willing_buyers)
            branch = "excess_demand_lottery"
        elif len(willing_sellers) > len(willing_buyers):
            rng.shuffle(willing_sellers)
            branch = "excess_supply_lottery"
        else:
            branch = "balanced_lottery"
        pairs = list(zip(
            willing_buyers[:quantity], willing_sellers[:quantity], strict=True
        ))
        payments = [
            PaymentRecord(
                buyer,
                seller,
                cross_price,
                "lottery_muda_cross_price",
                (case.product_id,),
            )
            for buyer, seller in pairs
        ]
        return pairs, payments, surplus, branch

    if rationing != "vickrey":
        raise ValueError(f"unknown MUDA rationing rule: {rationing}")

    if len(willing_buyers) > len(willing_sellers):
        selected_buyers = willing_buyers[:quantity]
        selected_sellers = willing_sellers
        buyer_payment = case.bids[willing_buyers[quantity]]
        seller_receipt = cross_price
        branch = "excess_demand_vickrey"
    elif len(willing_sellers) > len(willing_buyers):
        selected_buyers = willing_buyers
        selected_sellers = willing_sellers[:quantity]
        buyer_payment = cross_price
        seller_receipt = case.asks[willing_sellers[quantity]]
        branch = "excess_supply_vickrey"
    else:
        pairs = list(zip(willing_buyers, willing_sellers, strict=True))
        payments = [
            PaymentRecord(
                buyer,
                seller,
                cross_price,
                "vickrey_muda_balanced_cross_price",
                (case.product_id,),
            )
            for buyer, seller in pairs
        ]
        return pairs, payments, surplus, "balanced_vickrey"

    pairs = list(zip(selected_buyers, selected_sellers, strict=True))
    payments = []
    for buyer, seller in pairs:
        payments.extend((
            PaymentRecord(
                buyer,
                "platform",
                buyer_payment,
                "vickrey_muda_buyer_threshold",
                (case.product_id,),
            ),
            PaymentRecord(
                "platform",
                seller,
                seller_receipt,
                "vickrey_muda_seller_threshold",
                (case.product_id,),
            ),
        ))
        surplus += buyer_payment - seller_receipt
    return pairs, payments, surplus, branch


def _muda(case: TradeInput, seed: int, *, rationing: str) -> MarketOutcome:
    rng = np.random.default_rng(seed)
    left_buyers = [buyer for buyer in case.buyer_ids if rng.random() < 0.5]
    left_sellers = [seller for seller in case.seller_ids if rng.random() < 0.5]
    right_buyers = [buyer for buyer in case.buyer_ids if buyer not in left_buyers]
    right_sellers = [seller for seller in case.seller_ids if seller not in left_sellers]
    left_price = _equilibrium_price(case, left_buyers, left_sellers)
    right_price = _equilibrium_price(case, right_buyers, right_sellers)

    left = _muda_submarket(
        case,
        left_buyers,
        left_sellers,
        right_price,
        rationing=rationing,
        rng=rng,
    )
    right = _muda_submarket(
        case,
        right_buyers,
        right_sellers,
        left_price,
        rationing=rationing,
        rng=rng,
    )
    pairs = left[0] + right[0]
    payments = left[1] + right[1]
    surplus = left[2] + right[2]
    return _market_outcome(
        case,
        pairs,
        payments,
        {
            "trade_count": len(pairs),
            "auctioneer_surplus": surplus,
            "weak_budget_balance": surplus >= 0,
            "strong_budget_balance": surplus == 0,
            "left_price": left_price,
            "right_price": right_price,
            "left_buyers": left_buyers,
            "left_sellers": left_sellers,
            "right_buyers": right_buyers,
            "right_sellers": right_sellers,
            "left_branch": left[3],
            "right_branch": right[3],
            "rationing": rationing,
        },
    )


def clear_double(
    method_id: str,
    case: TradeInput,
    seed: int,
    params: Mapping[str, Any],
) -> MarketOutcome:
    del params
    if method_id in {"seller_price_double", "midpoint_double", "buyer_price_double"}:
        return _k_double(case, method_id)
    if method_id == "pay_as_bid_double":
        return _pay_as_bid(case)
    if method_id == "trade_reduction":
        return _trade_reduction(case)
    if method_id == "vcg_double_auction":
        return _vcg(case)
    if method_id == "sbba":
        return _sbba(case, seed)
    if method_id == "bilateral_midpoint":
        return _bilateral(case)
    if method_id == "random_sampling_double":
        return _random_sampling(case, seed)
    if method_id == "lottery_muda":
        return _muda(case, seed, rationing="lottery")
    if method_id == "vickrey_muda":
        return _muda(case, seed, rationing="vickrey")
    raise KeyError(f"unknown double-auction method: {method_id}")


__all__ = ["clear_double", "clear_single"]
