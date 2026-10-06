from __future__ import annotations

import json
from pathlib import Path

import yaml
from datamechbench.source_eligibility import (
    REQUIRED_SOURCE_CRITERIA,
    audit_source_candidate_catalog,
    write_source_candidate_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = (
    REPOSITORY_ROOT / "benchmark" / "catalog" / "direct_market_source_candidates.yaml"
)


def _candidate(*, status: str = "met", declared_status: str = "eligible") -> dict:
    return {
        "candidate_id": "fixture-source",
        "name": "Fixture source",
        "source_url": "https://example.org/source",
        "source_kind": "experimental_reservation_prices",
        "observable": "incentive-compatible seller reservation price",
        "proposed_use": "seller-cost calibration",
        "proposed_inference_unit": "participant",
        "declared_status": declared_status,
        "admission_scope": {
            "evidence_unit": "participant",
            "allowed_uses": ["seller-cost calibration"],
            "prohibited_uses": ["buyer-value calibration"],
        },
        "criteria": {
            criterion: {
                "status": status,
                "evidence": f"Direct evidence for {criterion}.",
                "limitation": f"Scope limit for {criterion}.",
            }
            for criterion in REQUIRED_SOURCE_CRITERIA
        },
    }


def test_eligible_candidate_requires_a_restricted_admission_scope(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "sources.yaml"
    candidate = _candidate()
    del candidate["admission_scope"]
    _write_catalog(catalog, [candidate])

    audit = audit_source_candidate_catalog(catalog)

    assert audit.valid is False
    assert audit.eligible_candidate_ids == ()
    assert audit.errors == (
        "candidate:fixture-source:eligible_source_missing_admission_scope",
    )


def _write_catalog(path: Path, candidates: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "audit_date": "2026-10-04",
                "eligibility_criteria": list(REQUIRED_SOURCE_CRITERIA),
                "candidates": candidates,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_all_eight_criteria_are_required_for_admission(tmp_path: Path) -> None:
    catalog = tmp_path / "sources.yaml"
    candidate = _candidate()
    candidate["criteria"]["reuse_rights"]["status"] = "unknown"
    candidate["criteria"]["reuse_rights"]["evidence"] = (
        "No dataset-specific reuse grant was located."
    )
    candidate["declared_status"] = "pending"
    _write_catalog(catalog, [candidate])

    audit = audit_source_candidate_catalog(catalog)

    assert audit.valid is True
    assert audit.eligible_candidate_ids == ()
    assert audit.pending_candidate_ids == ("fixture-source",)
    assert audit.decisions[0].blocking_criteria == ("reuse_rights",)


def test_attitude_only_source_cannot_satisfy_price_semantics(tmp_path: Path) -> None:
    catalog = tmp_path / "sources.yaml"
    candidate = _candidate(declared_status="ineligible")
    candidate["criteria"]["price_semantics"]["status"] = "not_met"
    candidate["criteria"]["price_semantics"]["evidence"] = (
        "The dataset records willingness-to-share Likert responses but no monetary type."
    )
    _write_catalog(catalog, [candidate])

    audit = audit_source_candidate_catalog(catalog)

    assert audit.valid is True
    assert audit.ineligible_candidate_ids == ("fixture-source",)
    assert audit.decisions[0].blocking_criteria == ("price_semantics",)


def test_declared_eligibility_cannot_override_missing_reuse_rights(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "sources.yaml"
    candidate = _candidate(declared_status="eligible")
    candidate["criteria"]["reuse_rights"]["status"] = "not_met"
    _write_catalog(catalog, [candidate])

    audit = audit_source_candidate_catalog(catalog)

    assert audit.valid is False
    assert audit.eligible_candidate_ids == ()
    assert audit.errors == (
        "candidate:fixture-source:declared_status_mismatch:"
        "declared=eligible:derived=ineligible",
    )


def test_current_candidate_ledger_admits_only_restricted_licensed_sources() -> None:
    audit = audit_source_candidate_catalog(DEFAULT_CATALOG)

    assert audit.valid is True
    assert audit.catalog == "benchmark/catalog/direct_market_source_candidates.yaml"
    assert audit.eligible_candidate_ids == ("ai-training-data-deals",)
    assert audit.candidate_count == 16
    decisions = {row.candidate_id: row for row in audit.decisions}
    data_deals = decisions["ai-training-data-deals"]
    assert data_deals.allowed_uses == (
        "deal-level pricing-mechanism landscape",
        "deal-level payment-disclosure audit",
        "reported-payment support envelope",
    )
    assert "seller reservation-cost calibration" in data_deals.prohibited_uses
    assert "mechanism outcome benchmarking" in data_deals.prohibited_uses
    assert "reuse_rights" in decisions["wu-secondary-monetization"].blocking_criteria
    assert "price_semantics" in decisions["tu-delft-mpc-sharing"].blocking_criteria
    assert "reproducible_access" in decisions["cnil-monetisation-survey"].blocking_criteria
    assert "reuse_rights" in decisions["ocean-polygon-settlements"].blocking_criteria
    assert "reproducible_access" in decisions["friehe-information-externalities"].blocking_criteria
    x_market = decisions["alizadeh-gilardi-x-marketplace"]
    assert x_market.criterion_statuses["reproducible_access"] == "met"
    assert x_market.criterion_statuses["reuse_rights"] == "not_met"
    assert x_market.criterion_statuses["privacy_safe"] == "not_met"
    assert x_market.criterion_statuses["transformation_audit"] == "not_met"
    assert x_market.blocking_criteria == (
        "reuse_rights",
        "privacy_safe",
        "transformation_audit",
    )
    privacy_wtp = decisions["skatova-privacy-protection-wtp"]
    assert privacy_wtp.criterion_statuses["price_semantics"] == "not_met"
    assert privacy_wtp.criterion_statuses["reuse_rights"] == "not_met"
    gps = decisions["hswen-gps-vickrey"]
    assert gps.criterion_statuses["reproducible_access"] == "not_met"
    assert gps.criterion_statuses["privacy_safe"] == "not_met"
    dp_wta = decisions["khavkin-toch-dp-wta"]
    assert dp_wta.criterion_statuses["institution_semantics"] == "met"
    assert dp_wta.criterion_statuses["price_semantics"] == "met"
    assert dp_wta.blocking_criteria == (
        "reproducible_access",
        "reuse_rights",
        "privacy_safe",
        "transformation_audit",
    )

    payload = audit.as_dict()
    assert payload["criterion_summary"]["price_semantics"] == {
        "met": 14,
        "not_met": 2,
        "unknown": 0,
        "blocking_count": 2,
    }
    assert payload["criterion_summary"]["reuse_rights"] == {
        "met": 3,
        "not_met": 9,
        "unknown": 4,
        "blocking_count": 13,
    }
    assert payload["criterion_summary"]["privacy_safe"] == {
        "met": 3,
        "not_met": 3,
        "unknown": 10,
        "blocking_count": 13,
    }
    assert payload["criterion_summary"]["transformation_audit"] == {
        "met": 4,
        "not_met": 2,
        "unknown": 10,
        "blocking_count": 12,
    }
    assert payload["admission_funnel"] == {
        "candidate_count": 16,
        "institution_and_price_semantics_met_count": 11,
        "release_trio_met_count": 2,
        "semantics_and_release_trio_met_count": 1,
        "fully_eligible_count": 1,
        "release_trio_criteria": [
            "reproducible_access",
            "reuse_rights",
            "privacy_safe",
        ],
        "interpretation_scope": "audited_candidate_set_not_literature_prevalence",
    }
    assert payload["blocking_criterion_count_distribution"] == {
        "0": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 6,
    }


def test_audit_writer_is_deterministic_and_preserves_negative_decisions(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "sources.yaml"
    _write_catalog(catalog, [_candidate()])
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    write_source_candidate_audit(catalog, first)
    write_source_candidate_audit(catalog, second)

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert payload["eligible_candidate_count"] == 1
    assert payload["ineligible_candidate_count"] == 0
    assert payload["pending_candidate_count"] == 0
    assert payload["eligible_candidate_ids"] == ["fixture-source"]
    assert payload["decisions"][0]["derived_status"] == "eligible"
