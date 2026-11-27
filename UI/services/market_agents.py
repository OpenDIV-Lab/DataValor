"""Deterministic, explainable order generation for workbench market agents."""

from __future__ import annotations

from typing import Any, Iterable


_BUYER_STYLE = {"conservative": 0.92, "balanced": 1.0, "aggressive": 1.08, "exploratory": 1.02}
_SELLER_STYLE = {"conservative": 1.08, "balanced": 1.0, "aggressive": 0.95, "exploratory": 1.02}
_SINGLE_PRODUCT_MECHANISMS = {
    "first_price_auction", "second_price_auction", "vcg",
    "mcafee_double_auction", "multi_unit_uniform_price",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, _number(value)))


def _latest(artifacts: Iterable[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    matches = [item for item in artifacts if item.get("kind") == kind]
    return max(matches, key=lambda item: str(item.get("created_at", "")), default=None)


def _evaluation_score(payload: dict[str, Any], fallback: float) -> float:
    values: list[float] = []
    for metric in payload.get("metrics", ()):
        if metric.get("value") is None:
            continue
        value = _clamp(metric.get("value"))
        if metric.get("direction") == "lower_is_better":
            value = 1 - value
        values.append(value)
    return sum(values) / len(values) if values else fallback


def market_signals(
    products: Iterable[dict[str, Any]],
    artifacts: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the latest comparable quality, valuation and price for each asset."""
    artifacts = tuple(artifacts)
    signals: dict[str, dict[str, Any]] = {}
    for product in products:
        product_id = str(product["product_id"])
        related = [
            item for item in artifacts
            if item.get("product_id") == product_id or product_id in item.get("product_ids", ())
        ]
        valuation = _latest(related, "valuation")
        pricing = _latest(related, "pricing")
        evaluation = _latest(related, "evaluation")
        estimates = (valuation or {}).get("payload", {}).get("estimates", ())
        quality = _clamp(product.get("metadata", {}).get("quality", 0.5))
        if evaluation:
            quality = _evaluation_score(evaluation.get("payload", {}), quality)
        latest_value = _number(estimates[0].get("value")) if estimates else None
        price_payload = (pricing or {}).get("payload", {}).get("price", {})
        latest_price = _number(price_payload.get("amount")) if price_payload.get("amount") is not None else None
        asking_price = _number(product.get("metadata", {}).get("asking_price"))
        price_basis = "latest_pricing_artifact"
        decision_price = latest_price
        if latest_price is None:
            decision_price = asking_price
            price_basis = "asking_price"
        elif asking_price > 0 and not 0.25 <= latest_price / asking_price <= 4:
            decision_price = asking_price
            price_basis = "asking_price_scale_guard"
        signals[product_id] = {
            "quality": round(quality, 6),
            "freshness": round(_clamp(product.get("metadata", {}).get("freshness", 0.5)), 6),
            "asking_price": asking_price,
            "latest_value": latest_value,
            "latest_price": latest_price,
            "decision_price": decision_price,
            "price_basis": price_basis,
            "currency": price_payload.get("currency") or product.get("metadata", {}).get("currency", "CNY"),
            "valuation_artifact_id": valuation.get("artifact_id") if valuation else None,
            "pricing_artifact_id": pricing.get("artifact_id") if pricing else None,
            "evaluation_artifact_id": evaluation.get("artifact_id") if evaluation else None,
        }
    return signals


def _preference_score(signal: dict[str, Any], preferences: dict[str, Any], max_price: float) -> float:
    weights = {
        "quality": max(0.0, _number(preferences.get("quality", 0.45))),
        "freshness": max(0.0, _number(preferences.get("freshness", 0.25))),
        "price": max(0.0, _number(preferences.get("price", 0.30))),
    }
    denominator = sum(weights.values()) or 1.0
    price = signal.get("decision_price") or signal.get("asking_price") or 0.0
    price_score = 1 - min(1.0, price / max_price) if max_price else 1.0
    return (
        weights["quality"] * signal["quality"]
        + weights["freshness"] * signal["freshness"]
        + weights["price"] * price_score
    ) / denominator


def generate_agent_orders(
    participants: Iterable[dict[str, Any]],
    products: Iterable[dict[str, Any]],
    artifacts: Iterable[dict[str, Any]],
    *,
    participant_ids: Iterable[str],
    product_ids: Iterable[str],
    mechanism: str,
) -> dict[str, Any]:
    """Generate editable orders from registered participant agent policies."""
    participant_ids = set(participant_ids)
    product_ids = set(product_ids)
    products = [item for item in products if item.get("product_id") in product_ids]
    participants = [item for item in participants if item.get("participant_id") in participant_ids]
    signals = market_signals(products, artifacts)
    max_price = max((signal.get("decision_price") or signal.get("asking_price") or 0 for signal in signals.values()), default=0)
    orders: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for participant in participants:
        participant_id = str(participant["participant_id"])
        role = participant.get("role")
        config = dict(participant.get("agent_config") or {})
        if not config.get("enabled", participant.get("delegation_mode") == "platform_managed"):
            skipped.append({"participant_id": participant_id, "reason": "agent_disabled"})
            continue
        preferred = set(config.get("preferred_mechanisms") or ())
        if preferred and mechanism not in preferred:
            skipped.append({"participant_id": participant_id, "reason": "mechanism_not_preferred"})
            continue
        model = str(config.get("model", "utility_maximizer" if role == "buyer" else "reserve_optimizer"))
        style = str(config.get("style", "balanced"))
        rationality = _clamp(config.get("rationality", 1.0))
        preferences = dict(config.get("preferences") or {})

        if role == "buyer":
            ranked = sorted(
                products,
                key=lambda item: _preference_score(signals[item["product_id"]], preferences, max_price),
                reverse=True,
            )
            if mechanism in _SINGLE_PRODUCT_MECHANISMS:
                ranked = ranked[:1]
            budget = _number(participant.get("budget"))
            remaining = budget
            bundle_mode = str(config.get("bundle_mode", preferences.get("bundle_mode", "single")))
            if model == "bundle_optimizer" and mechanism == "bundle_matching" and ranked:
                chosen = ranked
                anchors = [signals[item["product_id"]].get("latest_value") or signals[item["product_id"]].get("decision_price") or signals[item["product_id"]].get("asking_price") for item in chosen]
                amount = min(budget, sum(_number(value) for value in anchors) * _BUYER_STYLE.get(style, 1.0))
                orders.append({
                    "order_id": f"agent-bid-{participant_id}-bundle", "side": "bid", "participant_id": participant_id,
                    "product_ids": [item["product_id"] for item in chosen], "amount": round(amount, 2), "quantity": 1,
                    "currency": participant.get("currency", "CNY"), "bundle_mode": "and", "agent_generated": True,
                    "explanation": {"model": model, "style": style, "rationality": rationality, "reason": "bundle_utility_under_budget"},
                })
                continue
            for product in ranked:
                signal = signals[product["product_id"]]
                asking = signal.get("decision_price") or signal.get("asking_price") or 0.0
                value_anchor = signal.get("latest_value") or asking * (1 + signal["quality"] * 0.35)
                rational_bid = asking + rationality * (value_anchor - asking)
                amount = max(0.0, rational_bid * _BUYER_STYLE.get(style, 1.0))
                if budget:
                    amount = min(amount, remaining)
                if amount <= 0:
                    continue
                score = _preference_score(signal, preferences, max_price)
                orders.append({
                    "order_id": f"agent-bid-{participant_id}-{product['product_id']}", "side": "bid", "participant_id": participant_id,
                    "product_ids": [product["product_id"]], "amount": round(amount, 2), "quantity": 1,
                    "currency": participant.get("currency", signal["currency"]), "bundle_mode": bundle_mode, "agent_generated": True,
                    "explanation": {"model": model, "style": style, "rationality": rationality, "preference_score": round(score, 4), "value_anchor": round(value_anchor, 2), "reference_price": round(asking, 2), "price_basis": signal.get("price_basis")},
                })
                if budget:
                    remaining -= amount
                    if remaining <= 0:
                        break
        elif role == "seller":
            owned = set(participant.get("product_ids") or ())
            eligible = [item for item in products if item.get("owner_id") == participant_id or item.get("product_id") in owned]
            parameters = dict(participant.get("strategy_parameters") or {})
            markup = max(0.0, _number(parameters.get("markup", 0.08)))
            floor = max(0.0, _number(parameters.get("cost_floor", 0)))
            for product in eligible:
                signal = signals[product["product_id"]]
                asking = signal.get("asking_price") or 0.0
                market_price = signal.get("decision_price") or asking
                informed = market_price * (1 + markup)
                reserve = asking + rationality * (informed - asking)
                reserve = max(floor, reserve * _SELLER_STYLE.get(style, 1.0))
                orders.append({
                    "order_id": f"agent-ask-{participant_id}-{product['product_id']}", "side": "ask", "participant_id": participant_id,
                    "product_ids": [product["product_id"]], "amount": round(reserve, 2), "quantity": _number(parameters.get("quantity", 1), 1),
                    "currency": participant.get("currency", signal["currency"]), "bundle_mode": "single", "agent_generated": True,
                    "explanation": {"model": model, "style": style, "rationality": rationality, "markup": markup, "cost_floor": floor, "reference_price": round(market_price, 2), "price_basis": signal.get("price_basis")},
                })
        else:
            skipped.append({"participant_id": participant_id, "reason": "unsupported_role"})

    return {
        "orders": orders,
        "signals": signals,
        "diagnostics": {"generated": len(orders), "skipped": skipped, "mechanism": mechanism},
    }


__all__ = ["generate_agent_orders", "market_signals"]
