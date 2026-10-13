from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from datamechbench.models import (
    ProcurementCase,
    ProcurementInput,
    TradeCase,
    TradeInput,
)
from datamechbench.oracle_certification import (
    certify_reference_oracles,
    verify_oracle_certificate,
    write_oracle_certificate,
)
from datamechbench.report import write_jsonl
from datamechbench.runner import BenchmarkConfig, run_benchmark


def _cases() -> dict[str, tuple[object, ...]]:
    values = {"a": 4.0, "b": 4.0, "c": 7.0}
    costs = {"a": Decimal("2"), "b": Decimal("2"), "c": Decimal("4")}

    def utility(selected: tuple[str, ...]) -> float:
        return sum(values[item] for item in set(selected))

    procurement = ProcurementCase(
        case_id="p-certificate",
        public=ProcurementInput(
            seller_ids=("a", "b", "c"),
            reported_costs=costs,
            budget=Decimal("4"),
            utility=utility,
            seller_values=values,
        ),
        true_costs=costs,
        case_type="analytic",
    )
    trading = TradeCase(
        case_id="t-certificate",
        public=TradeInput(
            product_id="access",
            buyer_ids=("b0", "b1", "b2"),
            seller_ids=("s0", "s1", "s2"),
            bids={
                "b0": Decimal("10"),
                "b1": Decimal("8"),
                "b2": Decimal("3"),
            },
            asks={
                "s0": Decimal("1"),
                "s1": Decimal("5"),
                "s2": Decimal("4"),
            },
        ),
        true_values={
            "b0": Decimal("10"),
            "b1": Decimal("8"),
            "b2": Decimal("3"),
        },
        true_costs={
            "s0": Decimal("1"),
            "s1": Decimal("5"),
            "s2": Decimal("4"),
        },
        case_type="double_auction",
    )
    return {"valuation": (), "procurement": (procurement,), "trading": (trading,)}


def _results(cases: dict[str, tuple[object, ...]]):
    return run_benchmark(
        BenchmarkConfig(
            name="oracle-certificate-test",
            output_dir="unused",
            seeds=(0,),
            methods={
                "valuation": {},
                "procurement": {"budget_optimum": {}},
                "trading": {"efficient_clearing": {}},
            },
            case_ids={
                "valuation": (),
                "procurement": ("p-certificate",),
                "trading": ("t-certificate",),
            },
            strategic_audit=False,
        ),
        cases=cases,
    )


def test_exact_certificate_enumerates_finite_domains_and_agrees() -> None:
    cases = _cases()
    certificate = certify_reference_oracles(_results(cases), cases=cases)

    assert certificate["valid"] is True
    assert certificate["errors"] == []
    assert certificate["track_case_counts"] == {"procurement": 1, "trading": 1}
    procurement = next(row for row in certificate["cases"] if row["track"] == "procurement")
    trading = next(row for row in certificate["cases"] if row["track"] == "trading")
    assert procurement["domain_size"] == 8
    assert procurement["feasible_candidate_count"] == 5
    assert procurement["certified_selected_ids"] == ["a", "b"]
    assert procurement["certified_objective"] == 8.0
    assert trading["domain_size"] == 4
    assert trading["certified_trade_count"] == 2
    assert trading["certified_objective"] == "13"


def test_certificate_rejects_a_tampered_persisted_oracle_outcome() -> None:
    cases = _cases()
    results = _results(cases)
    target = next(row for row in results if row.track == "procurement")
    outcome = dict(target.outcome or {})
    outcome["selected_ids"] = ["c"]
    outcome["allocations"] = [
        {
            "actor_id": "c",
            "counterparty_id": "buyer",
            "product_ids": ["c"],
            "quantity": "1",
            "metadata": {},
        }
    ]
    tampered = tuple(
        replace(row, outcome=outcome) if row.run_id == target.run_id else row
        for row in results
    )

    certificate = certify_reference_oracles(tampered, cases=cases)

    assert certificate["valid"] is False
    assert any(error.startswith("oracle_disagreement:procurement:p-certificate") for error in certificate["errors"])


def test_certificate_file_is_hash_bound_and_semantically_verified(tmp_path: Path) -> None:
    cases = _cases()
    results_path = write_jsonl(_results(cases), tmp_path / "raw_results.jsonl")
    certificate_path = write_oracle_certificate(
        results_path,
        tmp_path / "oracle_certificate.json",
        cases=cases,
    )

    verification = verify_oracle_certificate(certificate_path)

    assert verification == {
        "valid": True,
        "errors": [],
        "case_count": 2,
        "track_case_counts": {"procurement": 1, "trading": 1},
    }

    payload = json.loads(certificate_path.read_text(encoding="utf-8"))
    payload["cases"][0]["certified_objective"] = 999.0
    certificate_path.write_text(json.dumps(payload), encoding="utf-8")
    tampered = verify_oracle_certificate(certificate_path)
    assert tampered["valid"] is False
    assert any("certified_optimum_mismatch" in error for error in tampered["errors"])
