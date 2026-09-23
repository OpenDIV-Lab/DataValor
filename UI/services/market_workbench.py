"""Multi-product market execution backed by DataValor mechanisms and analysis."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from datavalor.data_market import (
    BundleDemandMatcher,
    DemandClusterAnalyzer,
    Listing,
    ListingStatus,
    MarketGapAnalyzer,
    MarketSnapshot,
    MultiAttributeMarketMatcher,
    SupplySegmentAnalyzer,
    analyze_market_health,
    detect_market_anomalies,
)
from datavalor.data_price import (
    Ask,
    Bid,
    BudgetAwareProcurement,
    BudgetFeasibleProcurement,
    FirstPriceAuction,
    McAfeeDoubleAuction,
    Money,
    MultiUnitUniformPriceAuction,
    PricingOutcome,
    PricingRequest,
    QualityAwareProcurement,
    SecondPriceAuction,
    VCGMechanism,
    audit_pricing_outcome,
    evaluate_pricing_properties,
)

_MECHANISMS = {
    "first_price_auction": (FirstPriceAuction, "单品最高出价者按自身出价支付"),
    "second_price_auction": (SecondPriceAuction, "单品最高出价者按次高价支付"),
    "vcg": (VCGMechanism, "按外部性形成支付"),
    "mcafee_double_auction": (McAfeeDoubleAuction, "最高买价与最低卖价之间双边清算"),
    "budget_feasible_procurement": (BudgetFeasibleProcurement, "在采购预算内依次接受卖方"),
    "multi_unit_uniform_price": (MultiUnitUniformPriceAuction, "多单位按边际成交价统一支付"),
    "budget_aware_procurement": (BudgetAwareProcurement, "允许末笔部分数量的预算采购"),
    "quality_aware_procurement": (QualityAwareProcurement, "按质量成本比排序的预算采购"),
}


def market_schema() -> dict[str, Any]:
    mechanisms = {
        name: {
            "name": name,
            "label": description,
            "fields": ([{"key": "budget", "label": "采购预算", "type": "number", "default": 100000}, {"key": "buyer_id", "label": "采购方", "type": "text", "default": "buyer"}] if "procurement" in name else []) + ([{"key": "supply", "label": "各产品供给量", "type": "product_number_map", "default": {}}] if name == "multi_unit_uniform_price" else []),
        }
        for name, (_, description) in _MECHANISMS.items()
    }
    mechanisms["bundle_matching"] = {"name": "bundle_matching", "label": "AND/XOR 多产品组合需求匹配", "fields": [{"key": "budget", "label": "组合采购预算", "type": "number", "default": 100000}]}
    mechanisms["multi_attribute_matching"] = {"name": "multi_attribute_matching", "label": "价格、质量、新鲜度、信誉和权利多属性匹配", "fields": [{"key": "match_weights", "label": "匹配权重", "type": "json", "default": {"price": 0.4, "quality": 0.25, "freshness": 0.15, "reputation": 0.1, "rights": 0.1}}]}
    return {"mechanisms": mechanisms, "scenarios": {"single_auction": "单产品拍卖", "double_market": "双边市场", "procurement": "竞争采购", "multi_unit": "多单位市场", "bundle": "AND/XOR 组合需求", "multi_attribute": "多属性供需匹配"}}


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _product_ids(item: dict[str, Any], default_product: str) -> tuple[str, ...]:
    values = item.get("product_ids") or ([item["product_id"]] if item.get("product_id") else [default_product])
    return tuple(str(value) for value in values)


def _validate_products(ids: Iterable[str], known: set[str]) -> None:
    missing = sorted(set(ids) - known)
    if missing:
        raise ValueError(f"unknown product ids: {', '.join(missing)}")


def run_market(products, parameters: dict[str, Any], context):
    products = tuple(products)
    if not products:
        raise ValueError("market requires at least one product")
    known = {product.product_id for product in products}
    default_product = products[0].product_id
    default_currency = str(parameters.get("currency", "CNY"))
    currencies: set[str] = set()
    bids = []
    for index, item in enumerate(parameters.get("bids", ())):
        product_ids = _product_ids(item, default_product); _validate_products(product_ids, known)
        amount = _decimal(item.get("amount", 0), f"bids[{index}].amount"); quantity = _decimal(item.get("quantity", 1), f"bids[{index}].quantity")
        budget = item.get("budget")
        if amount < 0 or quantity < 0 or (budget is not None and _decimal(budget, f"bids[{index}].budget") < 0):
            raise ValueError("bid amount, budget and quantity must be non-negative")
        currency = str(item.get("currency", default_currency)); currencies.add(currency)
        bids.append(Bid(str(item.get("bid_id", f"bid-{index + 1}")), str(item.get("buyer_id", f"buyer-{index + 1}")), product_ids, Money(amount, currency), quantity, task_id=item.get("task_id"), constraints=dict(item.get("constraints", {})), metadata=dict(item.get("metadata", {}))))
    asks = []
    for index, item in enumerate(parameters.get("asks", ())):
        product_ids = _product_ids(item, default_product); _validate_products(product_ids, known)
        reserve = _decimal(item.get("reserve", 0), f"asks[{index}].reserve"); quantity = _decimal(item.get("quantity", 1), f"asks[{index}].quantity")
        if reserve < 0 or quantity < 0:
            raise ValueError("ask reserve and quantity must be non-negative")
        currency = str(item.get("currency", default_currency)); currencies.add(currency)
        asks.append(Ask(str(item.get("ask_id", f"ask-{index + 1}")), str(item.get("seller_id", f"seller-{index + 1}")), product_ids, Money(reserve, currency), quantity, constraints=dict(item.get("constraints", {})), metadata=dict(item.get("metadata", {}))))
    if len(currencies) > 1:
        raise ValueError("market orders must use a single currency")
    mechanism_name = str(parameters.get("mechanism", "mcafee_double_auction"))
    if not bids and not asks:
        raise ValueError("market requires at least one bid or ask")
    if "procurement" in mechanism_name and _decimal(parameters.get("budget", 0), "budget") < 0:
        raise ValueError("budget must be non-negative")

    supply_value = parameters.get("supply", {})
    supply = ({default_product: _decimal(supply_value, "supply")} if not isinstance(supply_value, dict) else {str(key): _decimal(value, f"supply.{key}") for key, value in supply_value.items()})
    unknown_supply = sorted(set(supply) - known)
    if unknown_supply:
        raise ValueError(f"unknown supply product ids: {', '.join(unknown_supply)}")
    if any(value < 0 for value in supply.values()):
        raise ValueError("supply must be non-negative")
    demand = {product_id: sum((bid.quantity for bid in bids if product_id in bid.product_ids), Decimal("0")) for product_id in known}
    market_context = {key: value for key, value in parameters.items() if key not in {"bids", "asks", "mechanism", "supply"}}
    request = PricingRequest(products, tuple(bids), tuple(asks), supply=supply, demand=demand, market_context=market_context)
    listings = tuple(Listing(f"listing-{index + 1}", product, product.owner_id, ListingStatus.ACTIVE, product.rights, metadata=dict(product.metadata)) for index, product in enumerate(products))
    single_product_mechanisms = {"first_price_auction", "second_price_auction", "vcg", "mcafee_double_auction", "multi_unit_uniform_price"}
    if mechanism_name in single_product_mechanisms:
        order_products = {product_id for order in (*bids, *asks) for product_id in order.product_ids}
        if len(order_products) != 1 or any(len(order.product_ids) != 1 for order in (*bids, *asks)):
            raise ValueError(f"{mechanism_name} requires bids and asks for the same single product")
    trace = [
        {"step": "normalize_orders", "status": "succeeded", "bids": len(bids), "asks": len(asks), "products": len(products)},
        {"step": "validate_market", "status": "succeeded", "currency": next(iter(currencies), default_currency), "supply": supply},
    ]
    bundle_selection = None
    multi_attribute_matches = ()
    if mechanism_name == "bundle_matching":
        bundle_selection = BundleDemandMatcher().resolve(bids, asks, Money(_decimal(parameters.get("budget", 0), "budget"), next(iter(currencies), default_currency)))
        outcome = PricingOutcome(mechanism_name, (), (), diagnostics={"selected_bundles": len(bundle_selection.matches)})
        trace.append({"step": "bundle_search", "status": "succeeded", "method": bundle_selection.method, "candidates": bundle_selection.diagnostics.get("candidate_count", 0), "selected": len(bundle_selection.matches)})
    elif mechanism_name == "multi_attribute_matching":
        multi_attribute_matches = MultiAttributeMarketMatcher().match(bids, asks, listings, weights=parameters.get("match_weights"))
        outcome = PricingOutcome(mechanism_name, (), (), diagnostics={"matches": len(multi_attribute_matches)})
        trace.append({"step": "multi_attribute_match", "status": "succeeded", "matches": len(multi_attribute_matches)})
    else:
        if mechanism_name not in _MECHANISMS:
            raise ValueError(f"market mechanism is not supported by the workbench: {mechanism_name}")
        mechanism = _MECHANISMS[mechanism_name][0]()
        outcome = mechanism.price(request, context)
        trace.append({"step": "clear_market", "status": "succeeded", "mechanism": mechanism_name, "allocations": len(outcome.allocations), "payments": len(outcome.payments)})

    budgets = {str(item.get("buyer_id")): _decimal(item["budget"], "budget") for item in parameters.get("bids", ()) if item.get("budget") is not None}
    snapshot = MarketSnapshot(listings, (), outcome)
    result = {
        "outcome": outcome,
        "bundle_selection": bundle_selection,
        "multi_attribute_matches": multi_attribute_matches,
        "properties": evaluate_pricing_properties(outcome, request, budgets=budgets or None),
        "audit": audit_pricing_outcome(outcome),
        "gaps": MarketGapAnalyzer().analyze(bids, asks, listings),
        "demand_segments": DemandClusterAnalyzer().analyze(bids),
        "supply_segments": SupplySegmentAnalyzer().analyze(listings, asks),
        "market_health": analyze_market_health(snapshot, bids, asks, outcome),
        "anomalies": detect_market_anomalies(listings, bids, asks),
        "order_book": {"bids": tuple(sorted(bids, key=lambda item: item.amount.amount, reverse=True)), "asks": tuple(sorted(asks, key=lambda item: item.reserve.amount))},
        "trace": trace + [{"step": "diagnostics", "status": "succeeded", "checks": ("properties", "audit", "gaps", "segments", "health", "anomalies")}],
    }
    return result, mechanism_name


__all__ = ["market_schema", "run_market"]
