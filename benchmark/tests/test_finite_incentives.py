from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from datamechbench.finite_incentives import (
    audit_procurement_method,
    audit_trading_method,
    load_finite_incentive_config,
    verify_finite_incentive_artifacts,
    write_finite_incentive_artifacts,
)
from datamechbench.models import AllocationRecord, MarketOutcome, PaymentRecord


class CriticalPriceProcurement:
    def allocate(self, case, seed):
        del seed
        seller = case.seller_ids[0]
        if case.reported_costs[seller] > Decimal("1"):
            return MarketOutcome()
        return MarketOutcome(
            selected_ids=(seller,),
            allocations=(AllocationRecord(seller, "buyer", (seller,)),),
            payments=(PaymentRecord("buyer", seller, Decimal("1"), "critical"),),
        )


class PayAsBidProcurement:
    def allocate(self, case, seed):
        del seed
        seller = case.seller_ids[0]
        report = case.reported_costs[seller]
        if report > case.budget:
            return MarketOutcome()
        return MarketOutcome(
            selected_ids=(seller,),
            allocations=(AllocationRecord(seller, "buyer", (seller,)),),
            payments=(PaymentRecord("buyer", seller, report, "reported"),),
        )


class SeedPriceTrade:
    def clear(self, case, seed):
        buyer = case.buyer_ids[0]
        seller = case.seller_ids[0]
        price = Decimal(seed % 2)
        return MarketOutcome(
            selected_ids=(buyer, seller),
            allocations=(AllocationRecord(buyer, seller, (case.product_id,)),),
            payments=(PaymentRecord(buyer, seller, price, "seed_price"),),
        )


def _procurement_config() -> dict[str, object]:
    return {
        "true_types": ["1", "2"],
        "reports": ["0", "1", "2"],
        "tolerance": "1e-9",
        "seller_ids": ["s0"],
        "public_values": {"s0": 4},
        "budget": "2",
        "seeds": [0],
        "stochastic": False,
        "expected_max_gain": "0",
        "expectation": "dominant-strategy source claim on the audited specialization",
    }


def _trading_config() -> dict[str, object]:
    return {
        "true_types": ["1", "2"],
        "reports": ["0", "1", "2"],
        "tolerance": "1e-9",
        "buyer_ids": ["b0"],
        "seller_ids": ["s0"],
        "seeds": [0, 1],
        "stochastic": True,
        "expected_max_gain": "0",
        "expectation": "fixed-seed report audit",
    }


def test_procurement_audit_enumerates_every_profile_actor_and_alternative_report():
    result = audit_procurement_method(
        "critical",
        CriticalPriceProcurement(),
        _procurement_config(),
        {"source": "toy", "reference_keys": ["toy"], "provenance_kind": "paper_exact"},
    )

    assert result["profile_count"] == 2
    assert result["seed_count"] == 1
    assert result["deviation_evaluation_count"] == 4
    assert result["expected_deviation_evaluation_count"] == 4
    assert result["max_gain"] == "0"
    assert result["profitable_deviation_count"] == 0
    assert result["conclusion"] == "no_counterexample_complete_finite_domain"
    assert result["report_domain_complete"] is True
    assert result["random_support_complete"] is True


def test_procurement_audit_retains_positive_witness_using_true_cost():
    result = audit_procurement_method(
        "pay_as_bid",
        PayAsBidProcurement(),
        _procurement_config(),
        {"source": "toy", "reference_keys": ["toy"], "provenance_kind": "common_baseline"},
    )

    assert result["max_gain"] == "1"
    assert result["conclusion"] == "counterexample_within_audited_domain"
    assert result["worst_witness"] == {
        "actor_id": "s0",
        "deviating_report": "2",
        "deviating_utility": "1",
        "gain": "1",
        "profile": {"s0": "1"},
        "seed": 0,
        "truthful_report": "1",
        "truthful_utility": "0",
    }


def test_trading_audit_reuses_seed_and_marks_random_support_incomplete():
    result = audit_trading_method(
        "seed_price",
        SeedPriceTrade(),
        _trading_config(),
        {"source": "toy", "reference_keys": ["toy"], "provenance_kind": "paper_variant"},
    )

    assert result["profile_count"] == 4
    assert result["seed_count"] == 2
    assert result["deviation_evaluation_count"] == 32
    assert result["max_gain"] == "0"
    assert result["random_support_complete"] is False
    assert result["estimand"] == "ex_post_fixed_seed_panel"
    assert result["conclusion"] == "no_counterexample_complete_reports_seed_panel"


@pytest.mark.parametrize(
    "mutation, match",
    [
        ({"true_types": []}, "true_types"),
        ({"reports": ["0", "1"]}, "contain every true type"),
        ({"tolerance": "NaN"}, "tolerance"),
        ({"seeds": []}, "seeds"),
    ],
)
def test_audit_rejects_malformed_domains(mutation, match):
    config = _procurement_config()
    config.update(mutation)
    with pytest.raises(ValueError, match=match):
        audit_procurement_method("critical", CriticalPriceProcurement(), config, {})


def test_writer_is_deterministic_and_verifier_detects_tampering(tmp_path: Path):
    record = audit_procurement_method(
        "critical",
        CriticalPriceProcurement(),
        _procurement_config(),
        {"source": "toy", "reference_keys": ["toy"], "provenance_kind": "paper_exact"},
    )
    result = {
        "schema_version": "1.0",
        "claim_strength": "empirical_finite_domain_audit",
        "methods": [record],
    }
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    evidence_a = tmp_path / "evidence-a.json"
    evidence_b = tmp_path / "evidence-b.json"

    write_finite_incentive_artifacts(result, out_a, evidence_a)
    write_finite_incentive_artifacts(result, out_b, evidence_b)

    assert (out_a / "audit_results.json").read_bytes() == (
        out_b / "audit_results.json"
    ).read_bytes()
    assert (out_a / "audit_results.csv").read_bytes() == (
        out_b / "audit_results.csv"
    ).read_bytes()
    assert verify_finite_incentive_artifacts(evidence_a)["valid"] is True
    assert "truthful" not in record["conclusion"].lower()
    (out_a / "audit_results.csv").write_text("tampered\n", encoding="utf-8")
    checked = verify_finite_incentive_artifacts(evidence_a)
    assert checked["valid"] is False
    assert checked["errors"] == ["sha256 mismatch: audit_results.csv"]


def test_config_loader_rejects_prohibited_conclusion_language(tmp_path: Path):
    path = tmp_path / "audit.yaml"
    path.write_text(
        "schema_version: '1.0'\nclaim_strength: proof of DSIC\ntrue_types: [1]\nreports: [0, 1]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="claim_strength"):
        load_finite_incentive_config(path)


def test_writer_rejects_incomplete_or_overclaimed_records(tmp_path: Path):
    record = audit_procurement_method(
        "critical",
        CriticalPriceProcurement(),
        _procurement_config(),
        {},
    )
    record["deviation_evaluation_count"] -= 1
    with pytest.raises(ValueError, match="incomplete deviation coverage"):
        write_finite_incentive_artifacts(
            {"schema_version": "1.0", "claim_strength": "empirical_finite_domain_audit", "methods": [record]},
            tmp_path / "out",
            tmp_path / "evidence.json",
        )


def test_evidence_manifest_is_json_and_repository_relative(tmp_path: Path):
    record = audit_procurement_method("critical", CriticalPriceProcurement(), _procurement_config(), {})
    evidence = tmp_path / "evidence.json"
    write_finite_incentive_artifacts(
        {"schema_version": "1.0", "claim_strength": "empirical_finite_domain_audit", "methods": [record]},
        tmp_path / "out",
        evidence,
    )
    manifest = json.loads(evidence.read_text(encoding="utf-8"))
    assert manifest["claim_strength"] == "empirical_finite_domain_audit"
    assert all(not Path(item["path"]).is_absolute() for item in manifest["artifacts"])
