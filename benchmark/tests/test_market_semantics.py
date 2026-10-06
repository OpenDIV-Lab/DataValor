from __future__ import annotations

import csv
import json
from pathlib import Path

from datamechbench.market_semantics import (
    DEFAULT_AGGREGATE_FINDINGS,
    DEFAULT_CATALOG,
    DEFAULT_DEAL_SNAPSHOT,
    DEFAULT_DIRECT_FINDINGS,
    DEFAULT_HELDOUT_MANIFESTS,
    DEFAULT_OCEAN_AUDIT,
    build_market_semantic_alignment,
    write_market_semantic_artifacts,
)


def test_real_market_alignment_keeps_six_non_substitutable_evidence_layers() -> None:
    alignment = build_market_semantic_alignment(
        snapshot_path=DEFAULT_DEAL_SNAPSHOT,
        catalog_path=DEFAULT_CATALOG,
        heldout_manifests=DEFAULT_HELDOUT_MANIFESTS,
        direct_findings_path=DEFAULT_DIRECT_FINDINGS,
        aggregate_findings_path=DEFAULT_AGGREGATE_FINDINGS,
        ocean_audit_path=DEFAULT_OCEAN_AUDIT,
    )

    assert alignment.valid is True
    assert [row.layer_id for row in alignment.layers] == [
        "task_utility",
        "cross_domain_proxy",
        "data_market_listing_ask",
        "aggregate_acceptance_anchor",
        "reported_data_licensing_deal",
        "executed_settlement_candidate",
    ]
    assert alignment.mechanism_outcome_replayable_layer_count == 0
    assert alignment.private_type_observed_layer_count == 0


def test_deal_semantics_quantifies_observability_and_dependence() -> None:
    alignment = build_market_semantic_alignment()
    deal = alignment.deal_evidence

    assert deal["row_count"] == 78
    assert deal["role_complete_count"] == 78
    assert deal["financial_terms_present_count"] == 35
    assert deal["reported_deal_amount_count"] == 7
    assert deal["high_confidence_reported_deal_amount_count"] == 2
    assert deal["pricing_mechanism_counts"] == {
        "aggregate": 71,
        "per_unit": 2,
        "unknown": 5,
    }
    assert deal["top_two_buyer_share"] == 0.5
    assert deal["record_iid_eligible"] is False
    assert deal["private_type_calibration_eligible"] is False
    assert deal["mechanism_outcome_eligible"] is False
    assert deal["mechanism_replayable_record_count"] == 0


def test_track_support_matrix_separates_real_support_from_forbidden_claims() -> None:
    alignment = build_market_semantic_alignment()
    matrix = {row.track: row for row in alignment.track_support}

    assert matrix["valuation"].performance_support == "direct_task_utility"
    assert (
        matrix["procurement"].performance_support
        == "task_utility_with_proxy_costs_and_listing_support"
    )
    assert (
        matrix["trading"].performance_support
        == "proxy_types_with_aggregate_geometry_sensitivity"
    )
    assert all(row.private_type_support == "none" for row in matrix.values())
    assert all(
        row.transaction_outcome_support == "none" for row in matrix.values()
    )
    assert "universal_deployment_performance" in alignment.forbidden_claims
    assert "observed_seller_reservation_cost" in alignment.forbidden_claims


def test_semantic_artifacts_are_machine_readable_and_consistent(tmp_path: Path) -> None:
    paths = write_market_semantic_artifacts(tmp_path)

    assert {path.name for path in paths} == {
        "market_semantic_alignment.json",
        "evidence_layers.csv",
        "track_claim_support.csv",
        "report.md",
    }
    payload = json.loads((tmp_path / "market_semantic_alignment.json").read_text())
    with (tmp_path / "evidence_layers.csv").open(newline="") as stream:
        layers = list(csv.DictReader(stream))
    with (tmp_path / "track_claim_support.csv").open(newline="") as stream:
        tracks = list(csv.DictReader(stream))

    assert payload["valid"] is True
    assert len(layers) == payload["layer_count"] == 6
    assert len(tracks) == 3
    assert "No licensed record supplies latent private types" in (
        tmp_path / "report.md"
    ).read_text(encoding="utf-8")
