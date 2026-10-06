from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from datamechbench.data_deal_evidence import (
    audit_data_deal_snapshot,
    classify_price_evidence,
    write_data_deal_evidence_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    REPOSITORY_ROOT
    / "benchmark"
    / "data"
    / "external"
    / "ai_data_deals_cc_by_4"
    / "snapshot.json"
)


def test_price_evidence_classifier_keeps_semantically_distinct_terms_apart() -> None:
    examples = {
        None: "missing",
        "undisclosed, multiyear": "undisclosed_or_non_numeric",
        "Est. total contract value: $25m - $50m": "estimated_or_revenue_proxy",
        "Other category revenue grew to $47M": "estimated_or_revenue_proxy",
        "Offers of $205 and $340 per title reported": "offer_or_unit_quote",
        "50% subscription revenue share": "share_only",
        "$250M+ over 5 years": "reported_deal_amount",
        "$42K/month or $2.5M/year.": "inconsistent_amount",
    }

    assert {
        value: classify_price_evidence(value) for value in examples
    } == examples


def test_frozen_snapshot_preserves_source_and_restricted_use_contract() -> None:
    audit = audit_data_deal_snapshot(DEFAULT_SNAPSHOT)

    assert audit.valid is True
    assert audit.source_dataset == "midah/ai-data-deals"
    assert audit.source_revision == "f8ce413790627e25138104d5f23d169430bb8aa6"
    assert audit.source_file_sha256 == (
        "4a5f21b2fe0d5afa1916899a5f19ed21fdb710841d0a5c649093cdcdff0abef7"
    )
    assert audit.license_id == "CC-BY-4.0"
    assert audit.row_count == 78
    assert audit.allowed_uses == (
        "deal-level pricing-mechanism landscape",
        "deal-level payment-disclosure audit",
        "reported-payment support envelope",
    )
    assert "seller reservation-cost calibration" in audit.prohibited_uses
    assert "mechanism outcome benchmarking" in audit.prohibited_uses


def test_evidence_funnel_prevents_public_deals_from_becoming_private_types() -> None:
    audit = audit_data_deal_snapshot(DEFAULT_SNAPSHOT)

    assert audit.price_evidence_counts == {
        "estimated_or_revenue_proxy": 8,
        "inconsistent_amount": 1,
        "missing": 43,
        "offer_or_unit_quote": 3,
        "reported_deal_amount": 7,
        "share_only": 7,
        "undisclosed_or_non_numeric": 9,
    }
    assert audit.reported_deal_amount_count == 7
    assert audit.high_confidence_reported_deal_amount_count == 2
    assert audit.private_type_calibration_eligible is False
    assert audit.mechanism_outcome_eligible is False


def test_market_structure_summary_uses_counterparty_blocks_not_rows() -> None:
    audit = audit_data_deal_snapshot(DEFAULT_SNAPSHOT)

    assert audit.pricing_mechanism_counts == {
        "aggregate": 71,
        "per_unit": 2,
        "unknown": 5,
    }
    assert audit.buyer_count == 18
    assert audit.seller_count == 56
    assert audit.top_buyer_row_count == 22
    assert audit.top_two_buyer_share == 0.5
    assert audit.invalid_modality_row_count == 2
    assert audit.role_complete_count == 78
    assert audit.financial_terms_present_count == 35
    assert audit.source_url_count == 78
    assert audit.known_exclusivity_count == 1
    assert audit.creator_compensation_reported_count == 7
    assert audit.use_case_counts == {
        "combined": 2,
        "rag": 32,
        "training": 41,
        "unknown": 3,
    }
    assert audit.record_iid_eligible is False
    assert audit.mechanism_replayable_record_count == 0


def test_duplicate_or_unclassified_rows_fail_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
    payload["rows"][1]["row_id"] = payload["rows"][0]["row_id"]
    payload["rows"][2]["price_evidence_class"] = ""
    broken = tmp_path / "snapshot.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_data_deal_snapshot(broken)

    assert audit.valid is False
    assert f"duplicate_row_id:{payload['rows'][0]['row_id']}" in audit.errors
    assert f"row:{payload['rows'][2]['row_id']}:invalid_price_evidence_class:" in audit.errors


def test_null_counterparty_and_unknown_pricing_mechanism_fail_closed(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
    payload["rows"][0]["buyer"] = None
    payload["rows"][0]["pricing_mechanism"] = "invented"
    broken = tmp_path / "snapshot.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_data_deal_snapshot(broken)

    assert audit.valid is False
    row_id = payload["rows"][0]["row_id"]
    assert f"row:{row_id}:missing_buyer" in audit.errors
    assert f"row:{row_id}:invalid_pricing_mechanism:invented" in audit.errors


def test_missing_required_use_restriction_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
    payload["use_contract"]["prohibited_uses"].remove(
        "seller reservation-cost calibration"
    )
    broken = tmp_path / "snapshot.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_data_deal_snapshot(broken)

    assert audit.valid is False
    assert audit.private_type_calibration_eligible is False
    assert (
        "use_contract:missing_prohibited_use:seller reservation-cost calibration"
        in audit.errors
    )


def test_report_writer_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_data_deal_evidence_report(DEFAULT_SNAPSHOT, first)
    write_data_deal_evidence_report(DEFAULT_SNAPSHOT, second)

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["row_count"] == 78
    assert payload["reported_deal_amount_count"] == 7
    assert payload["private_type_calibration_eligible"] is False


def test_native_python_cli_writes_the_audited_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "benchmark" / "src")

    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "benchmark" / "scripts" / "audit_ai_data_deals.py"),
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary == {
        "high_confidence_reported_deal_amount_count": 2,
        "output": str(output),
        "reported_deal_amount_count": 7,
        "row_count": 78,
        "valid": True,
    }
    assert json.loads(output.read_text(encoding="utf-8"))["valid"] is True
