"""Canonical, fail-closed serialization for benchmark mechanism outcomes."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .models import (
    AllocationRecord,
    MarketOutcome,
    PaymentRecord,
    ValuationOutput,
)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _identifiers(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    result = tuple(_identifier(item, f"{label} item") for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique identifiers")
    return result


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _finite_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    return value


def serialize_outcome(
    track: str, output: ValuationOutput | MarketOutcome
) -> dict[str, Any]:
    """Return the canonical public outcome payload used by trusted evaluators."""

    if track == "valuation":
        if not isinstance(output, ValuationOutput):
            raise ValueError("valuation outcome must be ValuationOutput")
        scores = {
            _identifier(owner, "score owner"): _finite_float(score, "score")
            for owner, score in sorted(output.scores.items())
        }
        if not scores:
            raise ValueError("valuation outcome scores must be non-empty")
        utility_calls = output.utility_calls
        if utility_calls is not None and (
            isinstance(utility_calls, bool)
            or not isinstance(utility_calls, int)
            or utility_calls < 0
        ):
            raise ValueError("utility_calls must be a non-negative integer or null")
        return {
            "kind": "valuation",
            "scores": scores,
            "diagnostics": _json_ready(output.diagnostics),
            "utility_calls": utility_calls,
        }
    if track not in {"procurement", "trading"}:
        raise ValueError(f"unsupported outcome track: {track}")
    if not isinstance(output, MarketOutcome):
        raise ValueError(f"{track} outcome must be MarketOutcome")
    return {
        "kind": "market",
        "selected_ids": list(output.selected_ids),
        "allocations": [
            {
                "actor_id": row.actor_id,
                "counterparty_id": row.counterparty_id,
                "product_ids": list(row.product_ids),
                "quantity": str(row.quantity),
                "metadata": _json_ready(row.metadata),
            }
            for row in output.allocations
        ],
        "payments": [
            {
                "payer_id": row.payer_id,
                "payee_id": row.payee_id,
                "amount": str(row.amount),
                "reason": row.reason,
                "product_ids": list(row.product_ids),
                "metadata": _json_ready(row.metadata),
            }
            for row in output.payments
        ],
        "diagnostics": _json_ready(output.diagnostics),
    }


def parse_outcome(
    track: str, payload: Mapping[str, Any]
) -> ValuationOutput | MarketOutcome:
    """Parse a canonical outcome payload without trusting submitted types."""

    raw = _mapping(payload, "outcome")
    if track == "valuation":
        if raw.get("kind") != "valuation":
            raise ValueError("valuation outcome kind must be valuation")
        raw_scores = _mapping(raw.get("scores"), "valuation scores")
        scores = {
            _identifier(owner, "score owner"): _finite_float(score, "score")
            for owner, score in raw_scores.items()
        }
        if not scores:
            raise ValueError("valuation outcome scores must be non-empty")
        diagnostics = _mapping(raw.get("diagnostics", {}), "outcome diagnostics")
        utility_calls = raw.get("utility_calls")
        if utility_calls is not None and (
            isinstance(utility_calls, bool)
            or not isinstance(utility_calls, int)
            or utility_calls < 0
        ):
            raise ValueError("utility_calls must be a non-negative integer or null")
        return ValuationOutput(scores, diagnostics, utility_calls)

    if track not in {"procurement", "trading"}:
        raise ValueError(f"unsupported outcome track: {track}")
    if raw.get("kind") != "market":
        raise ValueError("market outcome kind must be market")
    selected = _identifiers(raw.get("selected_ids", ()), "selected_ids")
    raw_allocations = raw.get("allocations", ())
    raw_payments = raw.get("payments", ())
    if not isinstance(raw_allocations, (list, tuple)):
        raise ValueError("allocations must be an array")
    if not isinstance(raw_payments, (list, tuple)):
        raise ValueError("payments must be an array")
    allocations = []
    for index, value in enumerate(raw_allocations):
        item = _mapping(value, f"allocation {index}")
        counterparty = item.get("counterparty_id")
        if counterparty is not None:
            counterparty = _identifier(counterparty, "allocation counterparty_id")
        allocations.append(
            AllocationRecord(
                actor_id=_identifier(item.get("actor_id"), "allocation actor_id"),
                counterparty_id=counterparty,
                product_ids=_identifiers(
                    item.get("product_ids", ()), "allocation product_ids"
                ),
                quantity=_finite_decimal(item.get("quantity", "1"), "quantity"),
                metadata=_mapping(
                    item.get("metadata", {}), "allocation metadata"
                ),
            )
        )
    payments = []
    for index, value in enumerate(raw_payments):
        item = _mapping(value, f"payment {index}")
        payments.append(
            PaymentRecord(
                payer_id=_identifier(item.get("payer_id"), "payment payer_id"),
                payee_id=_identifier(item.get("payee_id"), "payment payee_id"),
                amount=_finite_decimal(item.get("amount"), "payment amount"),
                reason=_identifier(item.get("reason"), "payment reason"),
                product_ids=_identifiers(
                    item.get("product_ids", ()), "payment product_ids"
                ),
                metadata=_mapping(item.get("metadata", {}), "payment metadata"),
            )
        )
    return MarketOutcome(
        selected_ids=selected,
        allocations=tuple(allocations),
        payments=tuple(payments),
        diagnostics=_mapping(raw.get("diagnostics", {}), "outcome diagnostics"),
    )


__all__ = ["parse_outcome", "serialize_outcome"]
