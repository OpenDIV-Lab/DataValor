from __future__ import annotations

import csv
from dataclasses import replace

import pytest
from datamechbench.leaderboard import summarize_leaderboard
from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.report import write_leaderboard_csvs, write_markdown_report


def _result(
    method: str,
    family: str,
    case: str,
    value,
    *,
    seed: int = 0,
    track: str = "valuation",
    role: str = "method",
    implementation: str = "native",
    setting: str = "valuation_game",
    pilot: bool = False,
    status: str = "completed",
):
    metric_name = {
        "valuation": "score_spearman",
        "procurement": "oracle_ratio",
        "trading": "gain_from_trade_ratio",
    }[track]
    metric = value if isinstance(value, MetricValue) else MetricValue(value)
    return BenchmarkResult(
        run_id=f"{method}-{case}-{seed}",
        track=track,
        method_id=method,
        case_id=case,
        seed=seed,
        status=status,
        metrics={metric_name: metric},
        runtime_seconds=0.1,
        metadata={
            "method_role": role,
            "method_family": family,
            "implementation_kind": implementation,
            "benchmark_setting": setting,
            "pilot": pilot,
        },
    )


def test_macro_average_gives_each_case_equal_weight_not_each_seed():
    rows = [
        *[_result("many", "many", "c1", 1.0, seed=seed) for seed in range(10)],
        _result("many", "many", "c2", 0.0),
        _result("steady", "steady", "c1", 0.6),
        _result("steady", "steady", "c2", 0.6),
    ]

    summary = summarize_leaderboard(rows, include_pilots=False)
    by_family = {row.family_id: row for row in summary}

    assert by_family["many"].mean == pytest.approx(0.5)
    assert by_family["many"].observation_count == 11
    assert by_family["many"].case_count == 2
    assert by_family["steady"].rank == 1
    assert by_family["many"].rank == 2


def test_canonical_family_prefers_native_and_oracle_never_ranks():
    rows = [
        _result("native", "shared", "c1", 0.4, implementation="native"),
        _result("adapter", "shared", "c1", 1.0, implementation="external_adapter"),
        _result("exact", "exact", "c1", 1.0, role="oracle"),
    ]

    summary = summarize_leaderboard(rows, include_pilots=False)

    assert [(row.family_id, row.method_id, row.mean, row.rank) for row in summary] == [
        ("shared", "native", 0.4, 1)
    ]


def test_competition_ties_and_confidence_intervals_are_defined():
    rows = [
        _result("a", "a", "c1", 0.5),
        _result("a", "a", "c2", 0.7),
        _result("b", "b", "c1", 0.6),
        _result("c", "c", "c1", 0.6),
    ]

    summary = {row.family_id: row for row in summarize_leaderboard(rows, include_pilots=False)}

    assert summary["a"].mean == pytest.approx(0.6)
    assert summary["a"].std == pytest.approx(2**0.5 / 10)
    assert summary["a"].ci95_low == pytest.approx(0.404)
    assert summary["a"].ci95_high == pytest.approx(0.796)
    assert summary["b"].ci95_low == summary["b"].ci95_high == 0.6
    assert {summary[name].rank for name in ("a", "b", "c")} == {1}

    rows.append(_result("d", "d", "c1", 0.5))
    ranked = {row.family_id: row.rank for row in summarize_leaderboard(rows, include_pilots=False)}
    assert ranked["d"] == 4


def test_na_family_is_retained_unranked_and_not_coerced_to_zero():
    summary = summarize_leaderboard(
        [_result("na", "na", "c1", MetricValue.na("missing_oracle_output"))],
        include_pilots=False,
    )

    assert len(summary) == 1
    assert summary[0].rank is None
    assert summary[0].mean is None
    assert summary[0].reason == "no_applicable_primary_metric"


def test_setting_and_pilot_filters_do_not_mix_stable_and_exploratory_rows():
    rows = [
        _result("formal", "formal", "c1", 0.5, setting="valuation_game"),
        _result(
            "pilot",
            "pilot",
            "c2",
            0.9,
            setting="valuation_owner_ml",
            pilot=True,
        ),
    ]

    stable = summarize_leaderboard(rows, include_pilots=False)
    selected = summarize_leaderboard(
        rows, include_pilots=True, setting="valuation_owner_ml", pilot_only=True
    )

    assert [row.family_id for row in stable] == ["formal"]
    assert [row.family_id for row in selected] == ["pilot"]
    assert selected[0].setting == "valuation_owner_ml"


def test_leaderboard_writers_emit_main_setting_statistics_and_markdown(tmp_path):
    procurement = _result(
        "p",
        "p",
        "p1",
        0.7,
        track="procurement",
        setting="procurement_additive",
    )
    procurement = replace(
        procurement,
        metrics={**procurement.metrics, "budget_violation": MetricValue(False)},
    )
    rows = [
        _result("v", "v", "c1", 0.5),
        procurement,
    ]

    paths = write_leaderboard_csvs(rows, tmp_path)
    report = write_markdown_report(rows, tmp_path / "report.md")

    assert {path.name for path in paths} == {
        "leaderboard_main.csv",
        "leaderboard_settings.csv",
        "metric_statistics.csv",
    }
    with (tmp_path / "leaderboard_main.csv").open(newline="", encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    assert {(row["track"], row["family_id"]) for row in records} == {
        ("valuation", "v"),
        ("procurement", "p"),
    }
    text = report.read_text(encoding="utf-8")
    assert "Main leaderboards" in text
    assert "Selected setting leaderboards" in text
    assert "Pilot evidence" in text
    assert "Constraint and audit statistics" in text
    assert "budget_violation" in text


def test_setting_uses_decision_specific_primary_metric_and_direction():
    good = _result("safe", "safe", "n1", 0.0, track="trading", setting="T-NO-TRADE")
    bad = _result("unsafe", "unsafe", "n1", 1.0, track="trading", setting="T-NO-TRADE")
    good = replace(good, metrics={"false_trade_count": MetricValue(0)})
    bad = replace(bad, metrics={"false_trade_count": MetricValue(2)})

    rows = summarize_leaderboard(
        [good, bad], include_pilots=False, setting="T-NO-TRADE"
    )

    assert rows[0].family_id == "safe"
    assert rows[0].primary_metric == "false_trade_count"
    assert rows[0].direction == "minimize"


def test_primary_metric_ineligible_control_case_is_not_ranked() -> None:
    control = _result(
        "method",
        "family",
        "clean",
        0.0,
        setting="V-REPLICATION-ROBUSTNESS",
    )
    attack = _result(
        "method",
        "family",
        "attack",
        0.0,
        setting="V-REPLICATION-ROBUSTNESS",
    )
    control = replace(
        control,
        metrics={"replication_owner_rank_change": MetricValue(0.0)},
        metadata={**control.metadata, "primary_metric_eligible": False},
    )
    attack = replace(
        attack,
        metrics={"replication_owner_rank_change": MetricValue(0.5)},
        metadata={**attack.metadata, "primary_metric_eligible": True},
    )

    (row,) = summarize_leaderboard(
        (control, attack),
        include_pilots=False,
        setting="V-REPLICATION-ROBUSTNESS",
    )

    assert row.mean == pytest.approx(0.5)
    assert row.case_count == 1
    assert row.eligible_case_count == 1
    assert row.coverage_ratio == 1.0


def test_coverage_is_reported_and_incomplete_methods_are_not_qualified():
    rows = [
        _result("complete", "complete", "c1", 0.6),
        _result("complete", "complete", "c2", 0.6),
        _result("partial", "partial", "c1", 0.9),
        _result("partial", "partial", "c2", MetricValue.na("unsupported")),
    ]

    summary = {row.family_id: row for row in summarize_leaderboard(rows, include_pilots=False)}

    assert summary["complete"].coverage_ratio == 1.0
    assert summary["complete"].qualified_rank == 1
    assert summary["partial"].raw_rank == 1
    assert summary["partial"].qualified_rank is None
    assert summary["partial"].reason == "insufficient_case_coverage"


def test_structurally_undefined_case_is_excluded_from_everyones_denominator():
    rows = [
        _result("a", "a", "trade", 0.8, track="trading", setting="T-DOUBLE"),
        _result("a", "a", "zero-gft", MetricValue.na("zero_efficient_gft"), track="trading", setting="T-DOUBLE"),
        _result("b", "b", "trade", 0.7, track="trading", setting="T-DOUBLE"),
        _result("b", "b", "zero-gft", MetricValue.na("zero_efficient_gft"), track="trading", setting="T-DOUBLE"),
    ]

    summary = summarize_leaderboard(rows, include_pilots=False, setting="T-DOUBLE")

    assert all(row.eligible_case_count == 1 for row in summary)
    assert all(row.coverage_ratio == 1.0 for row in summary)
