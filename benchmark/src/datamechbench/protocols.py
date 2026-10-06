"""Minimal method protocols used by the benchmark runner."""

from __future__ import annotations

from typing import Protocol

from .models import (
    MarketOutcome,
    MethodSpec,
    ProcurementInput,
    TradeInput,
    ValuationCase,
    ValuationOutput,
)


class ValuationMethod(Protocol):
    spec: MethodSpec

    def evaluate(self, case: ValuationCase, seed: int) -> ValuationOutput: ...


class ProcurementMethod(Protocol):
    spec: MethodSpec

    def allocate(self, case: ProcurementInput, seed: int) -> MarketOutcome: ...


class TradingMethod(Protocol):
    spec: MethodSpec

    def clear(self, case: TradeInput, seed: int) -> MarketOutcome: ...


__all__ = ["ProcurementMethod", "TradingMethod", "ValuationMethod"]
