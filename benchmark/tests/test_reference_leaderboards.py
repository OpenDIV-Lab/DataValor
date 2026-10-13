from __future__ import annotations

import csv
from pathlib import Path

from datamechbench.expectations import ExpectationSpec
from datamechbench.leaderboard import summarize_leaderboard
from datamechbench.models import BenchmarkResult
from datamechbench.report import write_research_artifacts


def _result(
    method: str,
    family: str,
    provenance: str,
    value: float,
    *,
    role: str = "method",
    implementation: str = "native",
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=method,
        track="valuation",
        method_id=method,
        case_id="case",
        seed=0,
        status="completed",
        metrics={"score_spearman": value},
        runtime_seconds=0.01,
        metadata={
            "method_family": family,
            "method_role": role,
            "implementation_kind": implementation,
            "provenance_kind": provenance,
            "benchmark_setting": "V-AXIOM",
            "case_assumptions": ["exact_coalition_utility"],
            "pilot": False,
        },
    )


def test_paper_view_excludes_baselines_diagnostics_and_oracles() -> None:
    rows = summarize_leaderboard(
        (
            _result("exact", "paper", "paper_exact", 0.9),
            _result("variant", "variant", "paper_variant", 0.8),
            _result("baseline", "baseline", "common_baseline", 1.0),
            _result("diagnostic", "diagnostic", "diagnostic_reference", 1.0),
            _result("oracle", "oracle", "allocation_oracle", 1.0, role="oracle"),
        ),
        include_pilots=False,
        view="paper",
    )

    assert {row.family_id for row in rows} == {"paper", "variant"}


def test_paper_view_canonicalizes_multiple_implementations() -> None:
    rows = summarize_leaderboard(
        (
            _result("native", "same", "paper_exact", 0.8),
            _result("official", "same", "official_adapter", 0.9, implementation="external_adapter"),
        ),
        include_pilots=False,
        view="paper",
    )

    assert len(rows) == 1
    assert rows[0].method_id == "native"


def test_all_view_excludes_allocation_oracle_even_if_registered_as_method() -> None:
    rows = summarize_leaderboard(
        (
            _result("method", "method", "paper_variant", 0.8),
            _result("relaxed", "relaxed", "allocation_oracle", 1.5),
        ),
        include_pilots=False,
        view="all",
    )

    assert {row.family_id for row in rows} == {"method"}


def test_research_artifacts_include_sources_settings_and_not_met_claims(
    tmp_path: Path,
) -> None:
    result = _result("exact", "paper", "paper_exact", 0.5)
    claim = ExpectationSpec(
        expectation_id="expected-perfect",
        family_id="paper",
        setting="V-AXIOM",
        metric_id="score_spearman",
        claim_kind="benchmark_sanity",
        relation="eq",
        target=1.0,
        tolerance=0.0,
        required_assumptions=("exact_coalition_utility",),
        reference_key="data_shapley",
        claim_location="test fixture",
    )

    paths = write_research_artifacts((result,), tmp_path, expectations=(claim,))

    assert {path.name for path in paths} == {
        "leaderboard_reference_main.csv",
        "leaderboard_reference_settings.csv",
        "method_sources.csv",
        "method_sources.md",
        "expectation_results.csv",
        "setting_cards.md",
        "property_results.csv",
        "metric_cards.md",
        "leaderboard_guide.md",
        "method_setting_matrix.csv",
        "constraint_leaderboard.csv",
        "mechanism_profiles.csv",
        "pairwise_comparisons.csv",
            "statistical_summary.md",
            "assumption_transfer.csv",
            "structural_curve_points.csv",
            "structural_profiles.csv",
            "structural_profiles.md",
            "discovery_findings.csv",
            "discovery_report.md",
            "deep_dive_auditability.csv",
            "deep_dive_market_thickness.csv",
            "deep_dive_replication.csv",
            "deep_dive_claim_aggregation.csv",
            "deep_dive_report.md",
        }
    with (tmp_path / "expectation_results.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["status"] == "not_met"
    assert (tmp_path / "method_sources.md").read_text(encoding="utf-8").count("| `") >= 48
    setting_cards = (tmp_path / "setting_cards.md").read_text(encoding="utf-8")
    assert "V-AXIOM" in setting_cards
    assert "Decision question:" in setting_cards
    assert "Primary metric:" in setting_cards
    assert "Interpretation boundary:" in setting_cards
    metric_cards = (tmp_path / "metric_cards.md").read_text(encoding="utf-8")
    assert "Question answered" in metric_cards
    assert "Failure modes" in metric_cards
    guide = (tmp_path / "leaderboard_guide.md").read_text(encoding="utf-8")
    assert "Qualified rank" in guide
    assert "Do not compare ranks across settings" in guide
