from __future__ import annotations

from decimal import Decimal

from datamechbench.distributive_incidence import analyze_group_incidence
from datamechbench.models import (
    BenchmarkResult,
    ProcurementCase,
    ProcurementInput,
)


def _case() -> ProcurementCase:
    sellers = ("s0", "s1", "s2", "s3")
    return ProcurementCase(
        case_id="case",
        public=ProcurementInput(
            seller_ids=sellers,
            reported_costs={
                "s0": Decimal("1"),
                "s1": Decimal("2"),
                "s2": Decimal("3"),
                "s3": Decimal("4"),
            },
            budget=Decimal("10"),
            utility=lambda selected: float(len(selected)),
        ),
        true_costs={
            "s0": Decimal("1"),
            "s1": Decimal("2"),
            "s2": Decimal("3"),
            "s3": Decimal("4"),
        },
        case_type="analytic",
        metadata={"provider_groups": {"s0": "small", "s1": "small", "s2": "large", "s3": "large"}},
    )


def _result(*, selected: tuple[str, ...], payments: tuple[tuple[str, str], ...]) -> BenchmarkResult:
    return BenchmarkResult(
        run_id="run",
        track="procurement",
        method_id="mechanism",
        case_id="case",
        seed=0,
        status="completed",
        metrics={},
        runtime_seconds=0.0,
        metadata={"evidence_scope": "controlled_induced_value"},
        outcome={
            "kind": "market",
            "selected_ids": list(selected),
            "allocations": [
                {"actor_id": seller, "quantity": "1", "product_ids": [seller], "metadata": {}}
                for seller in selected
            ],
            "payments": [
                {
                    "payer_id": "buyer",
                    "payee_id": seller,
                    "amount": amount,
                    "reason": "test",
                    "product_ids": [seller],
                    "metadata": {},
                }
                for seller, amount in payments
            ],
            "diagnostics": {},
        },
        schema_version="1.2",
    )


def test_group_incidence_uses_declared_member_denominators() -> None:
    rows = analyze_group_incidence(
        (_result(selected=("s0", "s2"), payments=(("s0", "3"), ("s2", "5"))),),
        {"case": _case()},
    )

    by_group = {row.group_id: row for row in rows}
    assert by_group["small"].group_member_count == 2
    assert by_group["small"].selected_count == 1
    assert by_group["small"].selection_rate == 0.5
    assert by_group["small"].payment_total == Decimal("3")
    assert by_group["small"].payment_share == 0.375
    assert by_group["small"].seller_surplus_total == Decimal("2")
    assert by_group["large"].seller_surplus_total == Decimal("2")


def test_zero_payment_denominator_is_finite_and_explicit() -> None:
    rows = analyze_group_incidence(
        (_result(selected=(), payments=()),), {"case": _case()}
    )

    assert len(rows) == 2
    assert all(row.selection_rate == 0.0 for row in rows)
    assert all(row.payment_share == 0.0 for row in rows)
    assert all(row.payment_denominator_status == "zero_total_payment" for row in rows)
    assert all(row.seller_surplus_total == Decimal("0") for row in rows)
