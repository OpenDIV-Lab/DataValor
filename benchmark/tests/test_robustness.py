from __future__ import annotations

from pathlib import Path

import pytest
from datamechbench.models import BenchmarkResult
from datamechbench.robustness import (
    load_assumption_transfers,
    summarize_assumption_transfers,
)


def _result(
    family: str,
    setting: str,
    case: str,
    value: float,
    *,
    track: str = "procurement",
) -> BenchmarkResult:
    metric = "oracle_ratio" if track == "procurement" else "gain_from_trade_ratio"
    guardrails = (
        {"budget_violation": 0.0, "seller_ir_violation_count": 0.0}
        if track == "procurement"
        else {"individual_rationality": 1.0, "weak_budget_balance": 1.0, "false_trade_count": 0.0}
    )
    return BenchmarkResult(
        run_id=f"{family}-{setting}-{case}",
        track=track,
        method_id=family,
        case_id=case,
        seed=0,
        status="completed",
        metrics={metric: value, **guardrails},
        runtime_seconds=0.01,
        metadata={
            "method_family": family,
            "benchmark_setting": setting,
            "implementation_kind": "native",
            "provenance_kind": "paper_exact",
            "pilot": False,
            "method_capabilities": [],
        },
    )


def _catalog(path: Path, body: str) -> Path:
    path.write_text("schema_version: '1.0'\ntransfers:\n" + body, encoding="utf-8")
    return path


def test_default_transfer_catalog_contains_selected_p_and_t_profiles() -> None:
    specs = load_assumption_transfers()

    assert {(row.source_setting, row.target_setting) for row in specs} == {
        ("P-SUBMODULAR", "P-ML-ACQUISITION"),
        ("T-DOUBLE", "T-CORRELATED"),
    }


def test_transfer_catalog_rejects_unknown_setting(tmp_path: Path) -> None:
    path = _catalog(
        tmp_path / "transfer.yaml",
        "  - {transfer_id: bad, track: trading, source_setting: T-DOUBLE, target_setting: T-UNKNOWN, rationale: test}\n",
    )

    with pytest.raises(ValueError, match="unknown setting"):
        load_assumption_transfers(path)


def test_transfer_catalog_rejects_metric_mismatch(tmp_path: Path) -> None:
    path = _catalog(
        tmp_path / "transfer.yaml",
        "  - {transfer_id: bad, track: trading, source_setting: T-DOUBLE, target_setting: T-NO-TRADE, rationale: test}\n",
    )

    with pytest.raises(ValueError, match="primary metric"):
        load_assumption_transfers(path)


def test_transfer_catalog_rejects_direction_mismatch(tmp_path: Path, monkeypatch) -> None:
    import datamechbench.robustness as module

    monkeypatch.setitem(module.SETTING_PRIMARY_METRICS, "T-REVERSED", ("gain_from_trade_ratio", "minimize"))
    path = _catalog(
        tmp_path / "transfer.yaml",
        "  - {transfer_id: bad, track: trading, source_setting: T-DOUBLE, target_setting: T-REVERSED, rationale: test}\n",
    )

    with pytest.raises(ValueError, match="direction"):
        load_assumption_transfers(path)


def test_transfer_summary_orients_delta_tracks_rank_and_retains_missing_family() -> None:
    rows = (
        _result("a", "P-SUBMODULAR", "s1", 0.8),
        _result("a", "P-SUBMODULAR", "s2", 0.8),
        _result("b", "P-SUBMODULAR", "s1", 0.7),
        _result("b", "P-SUBMODULAR", "s2", 0.7),
        _result("a", "P-ML-ACQUISITION", "t1", 0.6),
        _result("a", "P-ML-ACQUISITION", "t2", 0.6),
        _result("c", "P-ML-ACQUISITION", "t1", 0.9),
        _result("c", "P-ML-ACQUISITION", "t2", 0.9),
    )

    summary = summarize_assumption_transfers(rows)
    procurement = {row.family_id: row for row in summary if row.track == "procurement"}

    assert procurement["a"].status == "matched"
    assert procurement["a"].oriented_delta == pytest.approx(-0.2)
    assert procurement["a"].source_rank == 1
    assert procurement["a"].target_rank == 2
    assert procurement["a"].rank_change == 1
    assert procurement["b"].status == "missing_target"
    assert procurement["c"].status == "missing_source"
