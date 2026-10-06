from __future__ import annotations

import json
import shutil
from pathlib import Path

from datamechbench.external_validation import audit_external_implementation_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_official_mcafee_crosscheck_executes_five_branch_fixtures_and_builds_valid_record(
    tmp_path: Path,
) -> None:
    """A wrong local branch, price, GFT, or surplus must break this comparison."""

    from datamechbench.external_mcafee_validation import (
        build_official_mcafee_validation,
    )

    repository = tmp_path / "repo"
    external = repository / "benchmark/external/erelsgl_auctions"
    scripts = repository / "benchmark/scripts"
    evidence = repository / "benchmark/evidence"
    external.mkdir(parents=True)
    scripts.mkdir(parents=True)
    evidence.mkdir(parents=True)
    for name in (
        "agents.py",
        "markets.py",
        "trade.py",
        "mcafee_protocol.py",
        "LICENSE.txt",
        "mcafee_fixtures.json",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "benchmark/external/erelsgl_auctions" / name,
            external / name,
        )
    shutil.copy2(
        REPOSITORY_ROOT / "benchmark/scripts/run_external_mcafee_validation.py",
        scripts / "run_external_mcafee_validation.py",
    )

    result = build_official_mcafee_validation(
        external_directory=external,
        fixture_path=external / "mcafee_fixtures.json",
        runner_path=scripts / "run_external_mcafee_validation.py",
        output_directory=evidence,
        repository_root=repository,
    )

    assert result["fixture_count"] == 5
    assert result["all_close"] is True
    assert result["maximum_absolute_error"] == 0.0
    assert set(result["execution_environment"]) == {"python"}
    assert result["source_execution"] == (
        "upstream_files_with_one_terminal_newline_normalization"
    )
    assert result["source_normalizations"] == [{
        "path": "trade.py",
        "normalization": "one terminal newline appended by text vendoring",
        "upstream_sha256": (
            "41c23c1008d84c4bd8fce9d7bf6d8e7c68005c65187466ed84a32b820d53873f"
        ),
        "executed_sha256": (
            "851e2253d0bf9c2aecbb99fbaf44c4dc87c242d9123c68fd73ab0df239456ef4"
        ),
        "semantic_effect": "none",
    }]
    assert [item["case_id"] for item in result["comparisons"]] == [
        "candidate-price-full-trade",
        "candidate-price-rejected",
        "exhausted-side-reduction",
        "zero-gft-boundary",
        "no-trade",
    ]
    assert [item["branch"] for item in result["comparisons"]] == [
        "candidate_price",
        "trade_reduction",
        "trade_reduction",
        "candidate_price",
        "no_trade",
    ]
    assert all(
        item["observable_names"]
        == [
            "trade_count",
            "buyer_price",
            "seller_receipt",
            "realized_gain_from_trade",
            "auctioneer_surplus",
            "branch_code",
        ]
        for item in result["comparisons"]
    )

    record = evidence / "external_erelsgl_mcafee_results_v1.json"
    assert record.is_file()
    audit = audit_external_implementation_records(
        ("benchmark/evidence/external_erelsgl_mcafee_v1.json",),
        repository,
        expected_method_ids={"mcafee"},
        minimum_records=1,
        minimum_fixtures=5,
    )
    assert audit["passed"] is True
    assert audit["validated_method_ids"] == ["mcafee"]
    assert audit["official_upstream_count"] == 1

    stored = json.loads(record.read_text(encoding="utf-8"))
    assert stored == result


def test_official_mcafee_fallback_validates_standalone_trade_reduction(
    tmp_path: Path,
) -> None:
    """The standalone rule must match the pinned upstream fallback, not GTR."""

    from datamechbench.external_mcafee_validation import (
        build_official_trade_reduction_validation,
    )

    repository = tmp_path / "repo"
    external = repository / "benchmark/external/erelsgl_auctions"
    scripts = repository / "benchmark/scripts"
    evidence = repository / "benchmark/evidence"
    external.mkdir(parents=True)
    scripts.mkdir(parents=True)
    evidence.mkdir(parents=True)
    for name in (
        "agents.py",
        "markets.py",
        "trade.py",
        "mcafee_protocol.py",
        "LICENSE.txt",
        "trade_reduction_fixtures.json",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "benchmark/external/erelsgl_auctions" / name,
            external / name,
        )
    runner = scripts / "run_external_mcafee_validation.py"
    shutil.copy2(
        REPOSITORY_ROOT / "benchmark/scripts/run_external_mcafee_validation.py",
        runner,
    )

    result = build_official_trade_reduction_validation(
        external_directory=external,
        fixture_path=external / "trade_reduction_fixtures.json",
        runner_path=runner,
        output_directory=evidence,
        repository_root=repository,
    )

    assert result["fixture_count"] == 3
    assert result["all_close"] is True
    assert result["maximum_absolute_error"] == 0.0
    assert result["maximum_fixture_oracle_error"] == 0.0
    assert [item["case_id"] for item in result["comparisons"]] == [
        "candidate-price-rejected",
        "exhausted-side-reduction",
        "multi-unit-reduction",
    ]
    assert all(
        item["local_branch"] == item["external_branch"] == "trade_reduction"
        for item in result["comparisons"]
    )

    record_path = evidence / "external_erelsgl_trade_reduction_v1.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["method_id"] == "trade_reduction"
    assert "fallback branch" in record["claim_boundary"]
    assert "generalized" in record["claim_boundary"]
    assert record["external_implementation"]["source_url"].endswith(
        "/mcafee_protocol.py"
    )

    audit = audit_external_implementation_records(
        ("benchmark/evidence/external_erelsgl_trade_reduction_v1.json",),
        repository,
        expected_method_ids={"trade_reduction"},
        minimum_records=1,
        minimum_fixtures=3,
    )
    assert audit["passed"] is True
    assert audit["validated_method_ids"] == ["trade_reduction"]
    assert audit["official_upstream_count"] == 1
