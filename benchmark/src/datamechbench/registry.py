"""Explicit method registry and cross-track output validation."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from .models import (
    MarketOutcome,
    MethodSpec,
    ProcurementInput,
    TradeInput,
    ValuationCase,
    ValuationOutput,
)

Factory = Callable[[Mapping[str, Any]], Any]


class MethodRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[MethodSpec, Factory]] = {}

    def register(self, spec: MethodSpec, factory: Factory) -> None:
        if spec.method_id in self._entries:
            raise ValueError(f"method {spec.method_id!r} is already registered")
        self._entries[spec.method_id] = (spec, factory)

    def create(self, method_id: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            _, factory = self._entries[method_id]
        except KeyError as exc:
            raise KeyError(f"unknown method: {method_id}") from exc
        return factory(dict(params or {}))

    def specs(self, track: str | None = None) -> tuple[MethodSpec, ...]:
        values = [spec for spec, _ in self._entries.values() if track is None or spec.track == track]
        return tuple(sorted(values, key=lambda item: item.method_id))

    def compatible(self, track: str, case_type: str) -> tuple[MethodSpec, ...]:
        """Return methods that explicitly declare support for a case type."""

        return tuple(
            spec
            for spec in self.specs(track)
            if case_type in spec.supported_case_types
        )


def _finite_number(value: float | Decimal, label: str) -> None:
    finite = value.is_finite() if isinstance(value, Decimal) else math.isfinite(float(value))
    if not finite:
        raise ValueError(f"{label} must be finite")


def validate_output(
    spec: MethodSpec,
    case: ValuationCase | ProcurementInput | TradeInput,
    output: ValuationOutput | MarketOutcome,
) -> None:
    if spec.track == "valuation":
        if not isinstance(case, ValuationCase) or not isinstance(output, ValuationOutput):
            raise TypeError("valuation methods require ValuationCase and ValuationOutput")
        unknown = set(output.scores) - set(case.owner_ids)
        if unknown:
            raise ValueError(f"unknown owner IDs in output: {sorted(unknown)}")
        missing = set(case.owner_ids) - set(output.scores)
        if missing:
            raise ValueError(f"missing owner scores: {sorted(missing)}")
        for owner_id, value in output.scores.items():
            _finite_number(value, f"score for {owner_id}")
        return

    if not isinstance(output, MarketOutcome):
        raise TypeError("market methods require MarketOutcome")
    public_ids = (
        set(case.seller_ids)
        if isinstance(case, ProcurementInput)
        else set(case.buyer_ids) | set(case.seller_ids)
    )
    unknown_selected = set(output.selected_ids) - public_ids
    if unknown_selected:
        raise ValueError(f"unknown selected IDs: {sorted(unknown_selected)}")
    for allocation in output.allocations:
        if allocation.actor_id not in public_ids:
            raise ValueError(f"unknown allocation actor: {allocation.actor_id}")
        _finite_number(allocation.quantity, "allocation quantity")
        if allocation.quantity < 0:
            raise ValueError("allocation quantity must be non-negative")
    for payment in output.payments:
        if payment.payer_id not in public_ids and payment.payer_id not in {"buyer", "platform"}:
            raise ValueError(f"unknown payment payer: {payment.payer_id}")
        if payment.payee_id not in public_ids and payment.payee_id not in {"platform"}:
            raise ValueError(f"unknown payment payee: {payment.payee_id}")
        _finite_number(payment.amount, "payment amount")
        if payment.amount < 0:
            raise ValueError("payment amount must be non-negative")


__all__ = ["MethodRegistry", "validate_output"]
