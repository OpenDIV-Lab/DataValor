from __future__ import annotations

import json
from pathlib import Path

from datamechbench.induced_value_gold import (
    HEADLINE_METHODS,
    build_induced_value_gold,
    make_induced_value_cases,
    verify_induced_value_gold,
)
from datamechbench.report import load_jsonl_results


def test_gold_cases_are_deterministic_and_have_complete_induced_types() -> None:
    first = make_induced_value_cases()
    second = make_induced_value_cases()

    assert [case.case_id for case in first["procurement"]] == [
        case.case_id for case in second["procurement"]
    ]
    assert [case.case_id for case in first["trading"]] == [
        case.case_id for case in second["trading"]
    ]
    assert len(first["procurement"]) >= 4
    assert len(first["trading"]) >= 4
    for case in first["procurement"]:
        assert set(case.true_costs) == set(case.public.seller_ids)
        assert set(case.metadata["provider_groups"]) == set(case.public.seller_ids)
        assert case.metadata["evidence_scope"] == "controlled_induced_value"
        assert case.metadata["private_type_semantic"] == "induced_by_protocol"
        assert case.metadata["outcome_replayable"] is True
    for case in first["trading"]:
        assert set(case.true_values) == set(case.public.buyer_ids)
        assert set(case.true_costs) == set(case.public.seller_ids)
        assert set(case.metadata["provider_groups"]) == set(case.public.seller_ids)
        assert case.metadata["evidence_scope"] == "controlled_induced_value"
        assert case.metadata["private_type_semantic"] == "induced_by_protocol"


def test_gold_builder_runs_all_headline_methods_and_replays_outcomes(
    tmp_path: Path,
) -> None:
    summary = build_induced_value_gold(tmp_path, repository_root=Path.cwd())
    rows = load_jsonl_results(tmp_path / "raw_results.jsonl")

    assert summary["valid"] is True
    assert summary["failed_run_count"] == 0
    assert summary["headline_method_count"] == 11
    assert summary["replay_audit"]["metric_mismatch_count"] == 0
    assert summary["replay_audit"]["error_count"] == 0
    assert {row.method_id for row in rows if row.status == "completed"} == set(
        HEADLINE_METHODS["procurement"] + HEADLINE_METHODS["trading"]
    )
    assert all(row.schema_version == "1.2" for row in rows)
    assert all(row.outcome is not None for row in rows if row.status == "completed")

    semantic = json.loads((tmp_path / "semantic_receipt.json").read_text())
    assert semantic["direct_mechanism_semantics"] is True
    assert semantic["observed_market_private_types"] is False
    assert semantic["deployed_market_outcomes"] is False
    assert "not observed market preferences" in semantic["claim_boundary"]

    verification = verify_induced_value_gold(tmp_path / "manifest.json")
    assert verification == {"valid": True, "errors": [], "output_count": 5}


def test_gold_verifier_rejects_output_drift(tmp_path: Path) -> None:
    build_induced_value_gold(tmp_path, repository_root=Path.cwd())
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(summary_path.read_text() + " ", encoding="utf-8")

    verification = verify_induced_value_gold(tmp_path / "manifest.json")

    assert verification["valid"] is False
    assert verification["errors"] == ["hash_mismatch:summary.json"]
