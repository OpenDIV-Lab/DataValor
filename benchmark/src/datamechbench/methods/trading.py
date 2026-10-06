"""T-track adapters for single-sale and homogeneous double-auction cases."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_price import (
    Ask,
    Bid,
    McAfeeDoubleAuction,
    Money,
    PostedPriceMechanism,
    PricingRequest,
)

from ..models import (
    AllocationRecord,
    MarketOutcome,
    MethodSpec,
    PaymentRecord,
    TradeInput,
)
from ..registry import MethodRegistry
from .trading_double import clear_double, clear_single


def _spec(
    method_id: str,
    role: str,
    source: str,
    case_types: set[str],
    capabilities: set[str],
    *,
    stochastic: bool = False,
) -> MethodSpec:
    return MethodSpec(
        method_id=method_id,
        track="trading",
        role=role,
        source=source,
        version="1.0",
        stochastic=stochastic,
        capabilities=frozenset(capabilities),
        supported_case_types=frozenset(case_types),
    )


def _pricing_request(case: TradeInput) -> PricingRequest:
    product = DataProduct(
        case.product_id,
        case.product_id,
        DataReference(f"benchmark://product/{case.product_id}", "data_access"),
        case.seller_ids[0] if case.seller_ids else "platform",
    )
    bids = tuple(
        Bid(f"bid-{buyer}", buyer, (case.product_id,), Money(case.bids[buyer]))
        for buyer in case.buyer_ids
    )
    asks = tuple(
        Ask(f"ask-{seller}", seller, (case.product_id,), Money(case.asks[seller]))
        for seller in case.seller_ids
    )
    return PricingRequest((product,), bids=bids, asks=asks)


def _normalize(priced, case: TradeInput) -> MarketOutcome:
    allocations = []
    selected: list[str] = []
    default_seller = case.seller_ids[0] if len(case.seller_ids) == 1 else None
    for allocation in priced.allocations:
        seller = allocation.metadata.get("seller_id", default_seller)
        allocations.append(
            AllocationRecord(
                actor_id=allocation.buyer_id,
                counterparty_id=seller,
                product_ids=allocation.product_ids,
                quantity=allocation.quantity,
                metadata=dict(allocation.metadata),
            )
        )
        selected.append(allocation.buyer_id)
        if seller is not None:
            selected.append(str(seller))
    payments = tuple(
        PaymentRecord(
            payment.payer_id,
            payment.payee_id,
            payment.amount.amount,
            payment.reason,
            payment.product_ids,
            dict(payment.metadata),
        )
        for payment in priced.payments
    )
    return MarketOutcome(
        selected_ids=tuple(dict.fromkeys(selected)),
        allocations=tuple(allocations),
        payments=payments,
        diagnostics=dict(priced.diagnostics),
    )


@dataclass
class _TradingAdapter:
    spec: MethodSpec
    params: Mapping[str, Any]

    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        raise NotImplementedError


class _PostedPrice(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        del seed
        if case.posted_price is None:
            raise ValueError("posted_price method requires a precommitted case price")
        priced = PostedPriceMechanism(case.posted_price).price(
            _pricing_request(case), RunContext("benchmark")
        )
        normalized = _normalize(priced, case)
        return MarketOutcome(
            normalized.selected_ids,
            normalized.allocations,
            normalized.payments,
            {**normalized.diagnostics, "posted_price": str(case.posted_price)},
        )


class _SecondPrice(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        return clear_single("second_price", case, seed, self.params)


class _EfficientClearing(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        del seed
        bids = sorted(case.buyer_ids, key=lambda buyer: (-case.bids[buyer], buyer))
        asks = sorted(case.seller_ids, key=lambda seller: (case.asks[seller], seller))
        pairs = []
        for buyer, seller in zip(bids, asks):
            if case.bids[buyer] < case.asks[seller]:
                break
            pairs.append((buyer, seller))
        return MarketOutcome(
            selected_ids=tuple(actor for pair in pairs for actor in pair),
            allocations=tuple(
                AllocationRecord(buyer, seller, (case.product_id,)) for buyer, seller in pairs
            ),
            diagnostics={
                "trade_count": len(pairs),
                "payment_semantics": "not_applicable_allocation_oracle",
                "reported_gain_from_trade": str(
                    sum((case.bids[buyer] - case.asks[seller] for buyer, seller in pairs), Decimal("0"))
                ),
            },
        )


class _McAfee(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        del seed
        return _normalize(
            McAfeeDoubleAuction().price(_pricing_request(case), RunContext("benchmark")),
            case,
        )


class _ExpandedSingle(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        return clear_single(self.spec.method_id, case, seed, self.params)


class _ExpandedDouble(_TradingAdapter):
    def clear(self, case: TradeInput, seed: int) -> MarketOutcome:
        return clear_double(self.spec.method_id, case, seed, self.params)


def register_trading_methods(registry: MethodRegistry) -> None:
    entries = (
        (
            _spec(
                "posted_price",
                "baseline",
                "DataValor",
                {"single_sale"},
                {"allocations", "payments", "strategic_reports", "single_item"},
            ),
            _PostedPrice,
        ),
        (
            _spec(
                "second_price",
                "method",
                "DataValor",
                {"single_sale"},
                {"allocations", "payments", "strategic_reports", "single_item"},
            ),
            _SecondPrice,
        ),
        (
            _spec(
                "efficient_clearing",
                "oracle",
                "benchmark",
                {"double_auction"},
                {"allocations", "multi_party"},
            ),
            _EfficientClearing,
        ),
        (
            _spec(
                "mcafee",
                "method",
                "DataValor (McAfee 1992)",
                {"double_auction"},
                {"allocations", "payments", "strategic_reports", "multi_party"},
            ),
            _McAfee,
        ),
        (
            _spec("first_price", "method", "DataValor", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("second_price_reserve", "method", "Vickrey reserve auction", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("myerson_reserve", "method", "Myerson 1981", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("english_auction", "method", "English clock auction", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("dutch_auction", "method", "Dutch clock auction", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("all_pay", "method", "all-pay auction", {"single_sale"}, {"allocations", "payments", "strategic_reports", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("efficient_single_sale", "oracle", "benchmark", {"single_sale"}, {"allocations", "single_item"}),
            _ExpandedSingle,
        ),
        (
            _spec("vcg_double_auction", "method", "VCG double auction", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("pay_as_bid_double", "baseline", "benchmark", {"double_auction"}, {"allocations", "payments", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("seller_price_double", "method", "k-double auction", {"double_auction"}, {"allocations", "payments", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("midpoint_double", "method", "k-double auction", {"double_auction"}, {"allocations", "payments", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("buyer_price_double", "method", "k-double auction", {"double_auction"}, {"allocations", "payments", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("trade_reduction", "method", "McAfee 1992", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}),
            _ExpandedDouble,
        ),
        (
            _spec("sbba", "method", "Segal-Halevi et al. 2016", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}, stochastic=True),
            _ExpandedDouble,
        ),
        (
            _spec("random_sampling_double", "method", "random-sampling double auction", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}, stochastic=True),
            _ExpandedDouble,
        ),
        (
            _spec("lottery_muda", "method", "Segal-Halevi et al. MUDA", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}, stochastic=True),
            _ExpandedDouble,
        ),
        (
            _spec("vickrey_muda", "method", "Segal-Halevi et al. MUDA", {"double_auction"}, {"allocations", "payments", "strategic_reports", "multi_party"}, stochastic=True),
            _ExpandedDouble,
        ),
        (
            _spec("bilateral_midpoint", "baseline", "DataValor", {"double_auction"}, {"allocations", "payments", "multi_party"}),
            _ExpandedDouble,
        ),
    )
    for spec, adapter in entries:
        registry.register(spec, lambda params, spec=spec, adapter=adapter: adapter(spec, params))


__all__ = ["register_trading_methods"]
