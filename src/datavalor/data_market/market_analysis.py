"""Market matching and analysis methods over existing market contracts."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from statistics import pstdev
from typing import Any, Mapping, Sequence

from datavalor.data_price import Ask, Bid, Money, PricingOutcome

from .models import Listing, ListingStatus, MarketSnapshot


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception:
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def _unit(value: Any, default: str = "0") -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), _decimal(value, default)))


@dataclass(frozen=True)
class MultiAttributeMatch:
    bid_id: str
    ask_id: str
    buyer_id: str
    seller_id: str
    product_id: str
    quantity: Decimal
    score: Decimal
    score_components: Mapping[str, Decimal]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class MultiAttributeMarketMatcher:
    """Filter hard constraints, then rank feasible matches by explicit factors."""

    def match(
        self,
        bids: Sequence[Bid],
        asks: Sequence[Ask],
        listings: Sequence[Listing],
        *,
        weights: Mapping[str, Any] | None = None,
    ) -> tuple[MultiAttributeMatch, ...]:
        weights = {"price": Decimal("0.4"), "quality": Decimal("0.25"), "freshness": Decimal("0.15"), "reputation": Decimal("0.1"), "rights": Decimal("0.1"), **{str(name): max(Decimal("0"), _decimal(value)) for name, value in (weights or {}).items()}}
        listing_by_product = {item.product.product_id: item for item in listings if item.status is ListingStatus.ACTIVE}
        remaining = {ask.ask_id: max(Decimal("0"), ask.quantity) for ask in asks}
        candidates = []
        for bid in bids:
            if bid.quantity <= 0:
                continue
            for ask in asks:
                if bid.amount.currency != ask.reserve.currency or bid.amount.amount < ask.reserve.amount:
                    continue
                for product_id in sorted(set(bid.product_ids).intersection(ask.product_ids)):
                    listing = listing_by_product.get(product_id)
                    if listing is None:
                        continue
                    attributes = {**listing.product.metadata, **listing.metadata, **listing.terms}
                    quality = _unit(attributes.get("quality", 0)); freshness = _unit(attributes.get("freshness", 0)); reputation = _unit(attributes.get("reputation", 0)); rights_fit = _unit(attributes.get("rights_fit", 1), "1")
                    hard = {"quality": _decimal(bid.constraints.get("min_quality", 0)), "freshness": _decimal(bid.constraints.get("min_freshness", 0)), "reputation": _decimal(bid.constraints.get("min_reputation", 0)), "rights": _decimal(bid.constraints.get("min_rights_fit", 0))}
                    actual = {"quality": quality, "freshness": freshness, "reputation": reputation, "rights": rights_fit}
                    failed = tuple(name for name in hard if actual[name] < hard[name])
                    if failed:
                        continue
                    price_fit = _unit((bid.amount.amount - ask.reserve.amount) / bid.amount.amount if bid.amount.amount else 0)
                    components = {"price": price_fit, **actual}
                    denominator = sum(weights.get(name, Decimal("0")) for name in components)
                    score = sum(components[name] * weights.get(name, Decimal("0")) for name in components) / denominator if denominator else Decimal("0")
                    candidates.append((score, bid, ask, product_id, components))
        candidates.sort(key=lambda item: (-item[0], item[1].bid_id, item[2].ask_id, item[3]))
        matched_bids = set(); result = []
        for score, bid, ask, product_id, components in candidates:
            if bid.bid_id in matched_bids or remaining[ask.ask_id] <= 0:
                continue
            quantity = min(bid.quantity, remaining[ask.ask_id])
            if quantity <= 0:
                continue
            result.append(MultiAttributeMatch(bid.bid_id, ask.ask_id, bid.buyer_id, ask.seller_id, product_id, quantity, score, components, {"weights": weights, "surplus": (bid.amount.amount - ask.reserve.amount) * quantity}))
            remaining[ask.ask_id] -= quantity; matched_bids.add(bid.bid_id)
        return tuple(result)


@dataclass(frozen=True)
class MarketSegment:
    segment_id: str
    member_ids: tuple[str, ...]
    attributes: Mapping[str, Any]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class DemandClusterAnalyzer:
    """Create deterministic demand cohorts from existing bid attributes."""

    def analyze(self, bids: Sequence[Bid], fields: Sequence[str] = ("task_id", "budget_band", "region", "currency")) -> tuple[MarketSegment, ...]:
        groups: dict[tuple[str, ...], list[Bid]] = defaultdict(list)
        for bid in bids:
            values = []
            for name in fields:
                value = bid.task_id if name == "task_id" else bid.amount.currency if name == "currency" else bid.constraints.get(name, bid.metadata.get(name, "<missing>"))
                values.append(str(value if value is not None else "<missing>"))
            groups[tuple(values)].append(bid)
        return tuple(MarketSegment("demand:" + "|".join(key), tuple(sorted(item.bid_id for item in members)), dict(zip(fields, key)), {"buyer_count": len({item.buyer_id for item in members}), "total_quantity": sum((item.quantity for item in members), Decimal("0")), "mean_bid": sum((item.amount.amount for item in members), Decimal("0")) / Decimal(len(members))}) for key, members in sorted(groups.items()))


class SupplySegmentAnalyzer:
    """Segment active listings by declared quality, freshness, and price band."""

    @staticmethod
    def _band(value: Decimal, cuts: Sequence[Decimal]) -> str:
        return str(next((index for index, cut in enumerate(cuts) if value < cut), len(cuts)))

    def analyze(self, listings: Sequence[Listing], asks: Sequence[Ask] = (), *, quality_cuts: Sequence[Any] = (0.6, 0.85), freshness_cuts: Sequence[Any] = (0.5, 0.8), price_cuts: Sequence[Any] = (100, 500)) -> tuple[MarketSegment, ...]:
        asks_by_product = {product: ask for ask in asks for product in ask.product_ids}
        qcuts = tuple(_decimal(value) for value in quality_cuts); fcuts = tuple(_decimal(value) for value in freshness_cuts); pcuts = tuple(_decimal(value) for value in price_cuts)
        if any(left >= right for cuts in (qcuts, fcuts, pcuts) for left, right in zip(cuts, cuts[1:])):
            raise ValueError("segment cuts must be strictly increasing")
        groups: dict[tuple[str, ...], list[Listing]] = defaultdict(list)
        for listing in listings:
            if listing.status is not ListingStatus.ACTIVE:
                continue
            attrs = {**listing.product.metadata, **listing.metadata}; ask = asks_by_product.get(listing.product.product_id)
            key = (self._band(_decimal(attrs.get("quality")), qcuts), self._band(_decimal(attrs.get("freshness")), fcuts), self._band(ask.reserve.amount if ask else Decimal("0"), pcuts))
            groups[key].append(listing)
        return tuple(MarketSegment(f"supply:q{key[0]}-f{key[1]}-p{key[2]}", tuple(sorted(item.listing_id for item in members)), {"quality_band": key[0], "freshness_band": key[1], "price_band": key[2]}, {"listing_count": len(members), "seller_count": len({item.seller_id for item in members})}) for key, members in sorted(groups.items()))


@dataclass(frozen=True)
class MarketGap:
    product_id: str
    demand_quantity: Decimal
    supply_quantity: Decimal
    unmet_quantity: Decimal
    maximum_bid: Money | None
    minimum_ask: Money | None
    status: str


class MarketGapAnalyzer:
    """Describe unmet demand and price disconnects per product."""

    def analyze(self, bids: Sequence[Bid], asks: Sequence[Ask], listings: Sequence[Listing] = ()) -> tuple[MarketGap, ...]:
        active = {listing.product.product_id for listing in listings if listing.status is ListingStatus.ACTIVE} if listings else None
        products = sorted({product for bid in bids for product in bid.product_ids} | {product for ask in asks for product in ask.product_ids})
        result = []
        for product in products:
            product_bids = [bid for bid in bids if product in bid.product_ids]; product_asks = [ask for ask in asks if product in ask.product_ids and (active is None or product in active)]
            demand = sum((bid.quantity for bid in product_bids), Decimal("0")); supply = sum((ask.quantity for ask in product_asks), Decimal("0")); unmet = max(Decimal("0"), demand - supply)
            highest = max(product_bids, key=lambda item: item.amount.amount, default=None); lowest = min(product_asks, key=lambda item: item.reserve.amount, default=None)
            status = "no_supply" if demand and not supply else "price_gap" if highest and lowest and highest.amount.amount < lowest.reserve.amount else "undersupplied" if unmet else "balanced"
            result.append(MarketGap(product, demand, supply, unmet, highest.amount if highest else None, lowest.reserve if lowest else None, status))
        return tuple(result)


@dataclass(frozen=True)
class BundleMatch:
    bid_id: str
    buyer_id: str
    mode: str
    product_ids: tuple[str, ...]
    ask_ids: tuple[str, ...]
    total_reserve: Money
    reported_value: Money
    surplus: Money


@dataclass(frozen=True)
class BundleSelection:
    matches: tuple[BundleMatch, ...]
    total_cost: Money
    total_reported_value: Money
    unspent_budget: Money
    method: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class BundleDemandMatcher:
    """Resolve AND/XOR bundle bids and select recommendations under a budget."""

    def resolve(self, bids: Sequence[Bid], asks: Sequence[Ask], budget: Money, *, max_exact_candidates: int = 18) -> BundleSelection:
        if budget.amount < 0:
            raise ValueError("budget must be non-negative")
        ask_by_product: dict[str, Ask] = {}
        for ask in sorted(asks, key=lambda item: (item.reserve.amount, item.ask_id)):
            if ask.reserve.currency != budget.currency or ask.quantity < 1:
                continue
            for product in ask.product_ids:
                ask_by_product.setdefault(product, ask)
        candidates = []
        for bid in bids:
            if bid.amount.currency != budget.currency or bid.quantity <= 0 or not bid.product_ids:
                continue
            mode = str(bid.constraints.get("bundle_mode", "and")).lower()
            if mode not in {"and", "xor"}:
                raise ValueError("bundle_mode must be 'and' or 'xor'")
            product_sets = (tuple(bid.product_ids),) if mode == "and" else tuple((product,) for product in bid.product_ids)
            feasible = []
            for products in product_sets:
                selected_asks = [ask_by_product.get(product) for product in products]
                if any(ask is None for ask in selected_asks):
                    continue
                unique_asks = {ask.ask_id: ask for ask in selected_asks if ask}
                reserve = sum((ask.reserve.amount for ask in unique_asks.values()), Decimal("0")); surplus = bid.amount.amount - reserve
                if surplus >= 0:
                    feasible.append(BundleMatch(bid.bid_id, bid.buyer_id, mode, tuple(products), tuple(sorted(unique_asks)), Money(reserve, budget.currency), bid.amount, Money(surplus, budget.currency)))
            if feasible:
                candidates.append(max(feasible, key=lambda item: (item.surplus.amount, -item.total_reserve.amount, item.product_ids)))
        def feasible(selection):
            ask_ids = [ask_id for match in selection for ask_id in match.ask_ids]
            return len(ask_ids) == len(set(ask_ids)) and sum((match.total_reserve.amount for match in selection), Decimal("0")) <= budget.amount
        if len(candidates) <= max_exact_candidates:
            subsets = (combo for size in range(len(candidates) + 1) for combo in combinations(candidates, size))
            chosen = max((combo for combo in subsets if feasible(combo)), key=lambda combo: (sum((item.surplus.amount for item in combo), Decimal("0")), sum((item.reported_value.amount for item in combo), Decimal("0")), tuple(item.bid_id for item in combo)), default=())
            method = "exact_surplus"
        else:
            chosen_list = []
            for candidate in sorted(candidates, key=lambda item: (-item.surplus.amount, item.bid_id)):
                if feasible((*chosen_list, candidate)):
                    chosen_list.append(candidate)
            chosen = tuple(chosen_list); method = "greedy_surplus"
        cost = sum((item.total_reserve.amount for item in chosen), Decimal("0")); value = sum((item.reported_value.amount for item in chosen), Decimal("0"))
        return BundleSelection(tuple(chosen), Money(cost, budget.currency), Money(value, budget.currency), Money(budget.amount - cost, budget.currency), method, {"candidate_count": len(candidates), "unmatched_bid_ids": tuple(sorted({bid.bid_id for bid in bids} - {item.bid_id for item in candidates}))})


@dataclass(frozen=True)
class MarketHealthReport:
    metrics: Mapping[str, float | Decimal | None]
    by_group: Mapping[str, Mapping[str, float | int]]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def analyze_market_health(snapshot: MarketSnapshot, bids: Sequence[Bid] = (), asks: Sequence[Ask] = (), outcome: PricingOutcome | None = None, *, group_field: str = "group") -> MarketHealthReport:
    """Compute liquidity, competition, spread, and group exposure outcomes."""
    active = [item for item in snapshot.listings if item.status is ListingStatus.ACTIVE]
    seller_counts = Counter(item.seller_id for item in active); total_listings = sum(seller_counts.values())
    seller_hhi = sum((count / total_listings) ** 2 for count in seller_counts.values()) if total_listings else 0.0
    buyer_counts = Counter(bid.buyer_id for bid in bids); total_bids = sum(buyer_counts.values())
    buyer_hhi = sum((count / total_bids) ** 2 for count in buyer_counts.values()) if total_bids else 0.0
    currencies = {bid.amount.currency for bid in bids} | {ask.reserve.currency for ask in asks}
    best_bid = max((bid.amount.amount for bid in bids), default=None); best_ask = min((ask.reserve.amount for ask in asks), default=None)
    spread = best_ask - best_bid if len(currencies) <= 1 and best_bid is not None and best_ask is not None else None
    used_outcome = outcome or snapshot.latest_outcome; traded_products = {product for allocation in used_outcome.allocations for product in allocation.product_ids} if used_outcome else set()
    allocated_pairs = {(allocation.buyer_id, product) for allocation in used_outcome.allocations for product in allocation.product_ids} if used_outcome else set()
    unmatched = len({bid.bid_id for bid in bids if not any((bid.buyer_id, product) in allocated_pairs for product in bid.product_ids)})
    groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in active:
        groups[str(listing.metadata.get(group_field, listing.product.metadata.get(group_field, "<missing>")))].append(listing)
    by_group = {group: {"listings": len(items), "sellers": len({item.seller_id for item in items}), "traded_listings": sum(item.product.product_id in traded_products for item in items), "trade_rate": sum(item.product.product_id in traded_products for item in items) / len(items)} for group, items in sorted(groups.items())}
    payments = [payment.amount.amount for payment in used_outcome.payments] if used_outcome else []
    price_dispersion = Decimal(str(pstdev([float(value) for value in payments]))) if len(payments) > 1 else Decimal("0")
    return MarketHealthReport({"active_listings": len(active), "seller_count": len(seller_counts), "buyer_count": len(buyer_counts), "seller_hhi": seller_hhi, "buyer_hhi": buyer_hhi, "bid_ask_spread": spread, "unmatched_bid_count": unmatched, "trade_product_count": len(traded_products), "price_dispersion": price_dispersion}, by_group, {"group_field": group_field, "currencies": tuple(sorted(currencies)), "spread_available": len(currencies) <= 1})


@dataclass(frozen=True)
class MarketAnomaly:
    code: str
    severity: str
    actor_ids: tuple[str, ...]
    evidence: Mapping[str, Any]


def detect_market_anomalies(listings: Sequence[Listing], bids: Sequence[Bid], asks: Sequence[Ask], *, duplicate_price_tolerance: Decimal | float = Decimal("0"), high_price_quality_ratio: Decimal | float = Decimal("1000"), synchronized_bid_minimum: int = 3) -> tuple[MarketAnomaly, ...]:
    """Return review signals; no signal is treated as a fraud decision."""
    anomalies = []
    listing_groups: dict[tuple[str, str, Decimal], list[Listing]] = defaultdict(list)
    tolerance = max(Decimal("0"), _decimal(duplicate_price_tolerance)); ask_by_product = {product: ask for ask in asks for product in ask.product_ids}
    for listing in listings:
        ask = ask_by_product.get(listing.product.product_id); price = ask.reserve.amount if ask else Decimal("0")
        bucket = price if not tolerance else (price / tolerance).to_integral_value() * tolerance
        listing_groups[(listing.seller_id, listing.product.data.checksum or listing.product.data.uri, bucket)].append(listing)
        quality = _unit(listing.metadata.get("quality", listing.product.metadata.get("quality", 0)))
        if ask and quality > 0 and ask.reserve.amount / quality > _decimal(high_price_quality_ratio, "1000"):
            anomalies.append(MarketAnomaly("listing.high_price_low_quality", "medium", (listing.seller_id,), {"listing_id": listing.listing_id, "price_quality_ratio": ask.reserve.amount / quality}))
    for (seller, source, _), items in listing_groups.items():
        if len(items) > 1:
            anomalies.append(MarketAnomaly("listing.duplicate", "medium", (seller,), {"source": source, "listing_ids": tuple(sorted(item.listing_id for item in items))}))
    bid_groups = Counter((tuple(sorted(bid.product_ids)), bid.amount.currency, bid.amount.amount) for bid in bids)
    for key, count in bid_groups.items():
        if count >= synchronized_bid_minimum:
            actors = tuple(sorted({bid.buyer_id for bid in bids if (tuple(sorted(bid.product_ids)), bid.amount.currency, bid.amount.amount) == key}))
            anomalies.append(MarketAnomaly("bid.synchronized", "low", actors, {"product_ids": key[0], "amount": key[2], "count": count}))
    return tuple(anomalies)


__all__ = ["BundleDemandMatcher", "BundleMatch", "BundleSelection", "DemandClusterAnalyzer", "MarketAnomaly", "MarketGap", "MarketGapAnalyzer", "MarketHealthReport", "MarketSegment", "MultiAttributeMarketMatcher", "MultiAttributeMatch", "SupplySegmentAnalyzer", "analyze_market_health", "detect_market_anomalies"]
