from __future__ import annotations

import json
import shutil
from pathlib import Path

from datamechbench.external_validation import audit_external_implementation_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_official_sbba_specialization_validates_generic_domain_and_discloses_tie(
    tmp_path: Path,
) -> None:
    """A wrong branch, candidate support, price, expected GFT, or tie label must fail."""

    from datamechbench.external_sbba_validation import build_official_sbba_validation

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
        "trade_reduction_protocol.py",
        "LICENSE.txt",
        "sbba_fixtures.json",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "benchmark/external/erelsgl_auctions" / name,
            external / name,
        )
    runner = REPOSITORY_ROOT / "benchmark/scripts/run_external_sbba_validation.py"
    shutil.copy2(runner, scripts / runner.name)

    result = build_official_sbba_validation(
        external_directory=external,
        fixture_path=external / "sbba_fixtures.json",
        runner_path=scripts / runner.name,
        output_directory=evidence,
        repository_root=repository,
    )

    assert result["fixture_count"] == 5
    assert result["boundary_fixture_count"] == 1
    assert result["all_close"] is True
    assert result["maximum_absolute_error"] < 1e-12
    assert result["maximum_fixture_oracle_error"] < 1e-12
    assert result["source_execution"] == (
        "upstream_files_with_declared_terminal_newline_normalization"
    )
    assert [item["case_id"] for item in result["comparisons"]] == [
        "no-trade",
        "full-single-unit-external-competition",
        "full-two-unit-external-competition",
        "seller-lottery-two-candidates",
        "seller-lottery-three-candidates",
    ]
    assert all(
        item["observable_names"]
        == [
            "trade_count",
            "uniform_price",
            "buyer_candidate_count",
            "seller_candidate_count",
            "randomized_buyer",
            "randomized_seller",
            "expected_gain_from_trade",
            "strong_budget_balance",
            "branch_code",
        ]
        for item in result["comparisons"]
    )
    boundary = result["boundary_comparisons"]
    assert len(boundary) == 1
    assert boundary[0]["case_id"] == "zero-external-competition-tie"
    assert boundary[0]["status"] == "expected_semantic_boundary"
    assert boundary[0]["matches_declared_difference"] is True
    assert boundary[0]["local_scores"] == [3.0, 8.0, 3.0, 3.0, 0.0, 0.0, 17.0, 1.0, 1.0]
    assert boundary[0]["external_scores"] == [
        2.0,
        8.0,
        2.0,
        3.0,
        0.0,
        1.0,
        13.333333333333334,
        1.0,
        2.0,
    ]

    stored = json.loads(
        (evidence / "external_erelsgl_sbba_results_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == result
    audit = audit_external_implementation_records(
        ("benchmark/evidence/external_erelsgl_sbba_v1.json",),
        repository,
        expected_method_ids={"sbba"},
        minimum_records=1,
        minimum_fixtures=5,
    )
    assert audit["passed"] is True
    assert audit["validated_method_ids"] == ["sbba"]
    assert audit["official_upstream_count"] == 1


def test_official_sbba_specialization_rejects_misclassified_tie_boundary(
    tmp_path: Path,
) -> None:
    """The known tie divergence cannot be silently moved into validated agreement."""

    from datamechbench.external_sbba_validation import build_official_sbba_validation

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
        "trade_reduction_protocol.py",
        "LICENSE.txt",
        "sbba_fixtures.json",
    ):
        shutil.copy2(
            REPOSITORY_ROOT / "benchmark/external/erelsgl_auctions" / name,
            external / name,
        )
    runner = REPOSITORY_ROOT / "benchmark/scripts/run_external_sbba_validation.py"
    shutil.copy2(runner, scripts / runner.name)
    fixture_path = external / "sbba_fixtures.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    tie = dict(fixtures["boundary_cases"][0])
    tie["expected_branch"] = tie["expected_local_branch"]
    tie["expected_scores"] = tie["expected_local_scores"]
    fixtures["cases"].append(tie)
    fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")

    try:
        build_official_sbba_validation(
            external_directory=external,
            fixture_path=fixture_path,
            runner_path=scripts / runner.name,
            output_directory=evidence,
            repository_root=repository,
        )
    except ValueError as exc:
        assert "validated-domain fixture" in str(exc)
    else:
        raise AssertionError("misclassified SBBA boundary fixture was accepted")
