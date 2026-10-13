from __future__ import annotations

from decimal import Decimal

import pytest
from datamechbench.models import (
    AllocationRecord,
    BenchmarkResult,
    MarketOutcome,
    PaymentRecord,
    ValuationOutput,
)
from datamechbench.outcomes import parse_outcome, serialize_outcome


def test_valuation_outcome_round_trip_preserves_scores_and_diagnostics() -> None:
    original = ValuationOutput(
        scores={"owner-b": -0.25, "owner-a": 1.5},
        diagnostics={"branch": "exact", "nested": {"calls": 7}},
        utility_calls=11,
    )

    payload = serialize_outcome("valuation", original)

    assert payload == {
        "kind": "valuation",
        "scores": {"owner-a": 1.5, "owner-b": -0.25},
        "diagnostics": {"branch": "exact", "nested": {"calls": 7}},
        "utility_calls": 11,
    }
    assert parse_outcome("valuation", payload) == original


def test_market_outcome_round_trip_preserves_decimal_records() -> None:
    original = MarketOutcome(
        selected_ids=("seller-1",),
        allocations=(
            AllocationRecord(
                actor_id="buyer-1",
                counterparty_id="seller-1",
                product_ids=("dataset-a",),
                quantity=Decimal("0.1250"),
                metadata={"side": "buyer"},
            ),
        ),
        payments=(
            PaymentRecord(
                payer_id="buyer-1",
                payee_id="seller-1",
                amount=Decimal("10.2500"),
                reason="trade",
                product_ids=("dataset-a",),
            ),
        ),
        diagnostics={"uniform_price": "10.2500"},
    )

    payload = serialize_outcome("trading", original)

    assert payload["allocations"][0]["quantity"] == "0.1250"
    assert payload["payments"][0]["amount"] == "10.2500"
    assert parse_outcome("trading", payload) == original


@pytest.mark.parametrize(
    ("track", "payload", "message"),
    [
        ("valuation", {"kind": "market"}, "outcome kind"),
        (
            "valuation",
            {"kind": "valuation", "scores": {"a": float("nan")}},
            "finite",
        ),
        (
            "trading",
            {
                "kind": "market",
                "selected_ids": [],
                "allocations": [],
                "payments": [
                    {
                        "payer_id": "b",
                        "payee_id": "s",
                        "amount": "NaN",
                        "reason": "trade",
                        "product_ids": [],
                        "metadata": {},
                    }
                ],
                "diagnostics": {},
            },
            "finite",
        ),
    ],
)
def test_outcome_parser_fails_closed_on_malformed_payloads(
    track: str, payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_outcome(track, payload)


def test_schema_1_2_completed_result_requires_outcome() -> None:
    with pytest.raises(ValueError, match="completed schema 1.2 result requires outcome"):
        BenchmarkResult(
            run_id="run",
            track="valuation",
            method_id="method",
            case_id="case",
            seed=0,
            status="completed",
            metrics={},
            runtime_seconds=0.0,
            schema_version="1.2",
        )


def test_schema_1_2_noncompleted_result_rejects_outcome() -> None:
    with pytest.raises(ValueError, match="non-completed result cannot carry outcome"):
        BenchmarkResult(
            run_id="run",
            track="valuation",
            method_id="method",
            case_id="case",
            seed=0,
            status="failed",
            metrics={},
            runtime_seconds=0.0,
            error="failure",
            outcome={"kind": "valuation", "scores": {"a": 1.0}},
            schema_version="1.2",
        )
