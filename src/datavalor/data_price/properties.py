"""Executable mechanism properties and witness diagnostics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import PricingOutcome, PricingRequest


def check_individual_rationality(outcome: PricingOutcome, request: PricingRequest) -> dict[str, Any]:
    # Bid.amount is a unit willingness-to-pay when quantity bids are used.
    # Compare payments with the value of the actually allocated quantity.
    bids = {}
    for bid in request.bids:
        bids.setdefault(bid.buyer_id, Decimal("0"))
        bids[bid.buyer_id] += bid.amount.amount * max(Decimal("0"), bid.quantity)
    paid = {}
    for payment in outcome.payments:
        paid[payment.payer_id] = paid.get(payment.payer_id, Decimal("0")) + payment.amount.amount
    violations = {buyer: {"bid": bids[buyer], "paid": amount} for buyer, amount in paid.items() if buyer in bids and amount > bids[buyer]}
    return {"property": "individual_rationality", "holds": not violations, "violations": violations}


def check_budget_feasibility(outcome: PricingOutcome, budgets: dict[str, Decimal]) -> dict[str, Any]:
    spent = {}
    for payment in outcome.payments:
        spent[payment.payer_id] = spent.get(payment.payer_id, Decimal("0")) + payment.amount.amount
    violations = {actor: {"budget": Decimal(str(budgets[actor])), "spent": amount} for actor, amount in spent.items() if actor in budgets and amount > Decimal(str(budgets[actor]))}
    return {"property": "budget_feasibility", "holds": not violations, "violations": violations}


def check_capacity_feasibility(outcome: PricingOutcome, supply: dict[str, Decimal]) -> dict[str, Any]:
    allocated = {}
    for allocation in outcome.allocations:
        for product_id in allocation.product_ids:
            allocated[product_id] = allocated.get(product_id, Decimal("0")) + allocation.quantity
    violations = {product_id: {"supply": Decimal(str(supply[product_id])), "allocated": quantity} for product_id, quantity in allocated.items() if product_id in supply and quantity > Decimal(str(supply[product_id]))}
    return {"property": "capacity_feasibility", "holds": not violations, "violations": violations}


def evaluate_pricing_properties(outcome: PricingOutcome, request: PricingRequest, *, budgets: dict[str, Decimal] | None = None) -> dict[str, Any]:
    checks = {"individual_rationality": check_individual_rationality(outcome, request), "capacity_feasibility": check_capacity_feasibility(outcome, {key: Decimal(str(value)) for key, value in request.supply.items()})}
    if budgets is not None:
        checks["budget_feasibility"] = check_budget_feasibility(outcome, budgets)
    return checks


__all__ = ["check_budget_feasibility", "check_capacity_feasibility", "check_individual_rationality", "evaluate_pricing_properties"]
