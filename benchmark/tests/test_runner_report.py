from __future__ import annotations

from dataclasses import replace

from datamechbench.data import make_analytic_valuation_cases, make_trade_cases
from datamechbench.methods.trading import register_trading_methods
from datamechbench.methods.valuation import OptionalMethodUnavailable, register_valuation_methods
from datamechbench.models import MarketOutcome, MethodSpec, ValuationOutput
from datamechbench.registry import MethodRegistry
from datamechbench.report import (
    load_jsonl_results,
    write_jsonl,
    write_markdown_report,
    write_track_csvs,
)
from datamechbench.runner import BenchmarkConfig, build_cases, run_benchmark


class _EchoValuation:
    def __init__(self, spec):
        self.spec = spec

    def evaluate(self, case, seed):
        return ValuationOutput({owner: float(seed) for owner in case.owner_ids})


class _SkipValuation(_EchoValuation):
    def evaluate(self, case, seed):
        raise OptionalMethodUnavailable("optional_dependency_missing:test")


class _FailValuation(_EchoValuation):
    def evaluate(self, case, seed):
        raise RuntimeError("deliberate failure")


class _NoTrade:
    def __init__(self, spec):
        self.spec = spec

    def clear(self, case, seed):
        return MarketOutcome()


def _spec(method_id, track, *, stochastic=False):
    return MethodSpec(
        method_id=method_id,
        track=track,
        role="baseline",
        source="test",
        version="1",
        stochastic=stochastic,
        capabilities=frozenset({"scores"}) if track == "valuation" else frozenset({"allocations"}),
        supported_case_types=frozenset({"analytic"}) if track == "valuation" else frozenset({"single_sale"}),
    )


def _registry():
    registry = MethodRegistry()
    register_valuation_methods(registry)
    register_trading_methods(registry)
    for method_id, cls in (("test_echo", _EchoValuation), ("test_skip", _SkipValuation), ("test_fail", _FailValuation)):
        spec = _spec(method_id, "valuation")
        registry.register(spec, lambda params, spec=spec, cls=cls: cls(spec))
    trade_spec = _spec("test_no_trade", "trading")
    registry.register(trade_spec, lambda params: _NoTrade(trade_spec))
    return registry


def test_runner_retains_statuses_and_has_deterministic_ids():
    config = BenchmarkConfig(
        name="tiny",
        output_dir="unused",
        seeds=(3, 4),
        methods={
            "valuation": {
                "random": {},
                "test_echo": {},
                "test_skip": {},
                "test_fail": {},
            },
            "procurement": {},
            "trading": {"test_no_trade": {}},
        },
        case_ids={
            "valuation": ("C-add",),
            "procurement": (),
            "trading": ("S5-single-sale",),
        },
        strategic_audit=False,
    )
    cases = {
        "valuation": (make_analytic_valuation_cases()[0],),
        "procurement": (),
        "trading": (make_trade_cases(seed=42)[0],),
    }
    first = run_benchmark(config, registry=_registry(), cases=cases)
    second = run_benchmark(config, registry=_registry(), cases=cases)

    assert [result.run_id for result in first] == [result.run_id for result in second]
    assert len(first) == 6
    assert {result.status for result in first} == {"completed", "skipped", "failed"}
    assert next(result for result in first if result.method_id == "test_skip").error == "optional_dependency_missing:test"
    assert "deliberate failure" in next(result for result in first if result.method_id == "test_fail").error
    assert all(result.schema_version == "1.2" for result in first)
    assert all(
        (result.outcome is not None) == (result.status == "completed")
        for result in first
    )
    valuation = next(
        result
        for result in first
        if result.method_id == "test_echo" and result.status == "completed"
    )
    assert valuation.outcome == {
        "kind": "valuation",
        "scores": {
            "o0": 3.0,
            "o1": 3.0,
            "o2": 3.0,
            "o3": 3.0,
            "o4": 3.0,
            "o5": 3.0,
        },
        "diagnostics": {},
        "utility_calls": None,
    }
    trading = next(
        result
        for result in first
        if result.method_id == "test_no_trade" and result.status == "completed"
    )
    assert trading.outcome == {
        "kind": "market",
        "selected_ids": [],
        "allocations": [],
        "payments": [],
        "diagnostics": {
            "resource_usage": {
                "submitted_reports": 11,
                "clearing_passes": 1,
                "randomization_events": 0,
            }
        },
    }
    assert any(result.method_id == "test_echo" for result in first)
    assert any(result.method_id == "test_no_trade" for result in first)
    assert all(result.metadata["method_family"] for result in first)
    cataloged = next(result for result in first if result.method_id == "random")
    assert cataloged.metadata["provenance_kind"] == "common_baseline"
    assert cataloged.metadata["reference_keys"] == ["datamechbench_repo"]
    assert cataloged.metadata["metric_catalog_version"] == "1.2"
    assert cataloged.metadata["case_assumptions"] == []
    custom = next(result for result in first if result.method_id == "test_echo")
    assert custom.metadata["provenance_kind"] == "paper_variant"


def test_runner_preserves_structural_axis_metadata() -> None:
    case = replace(
        make_analytic_valuation_cases()[0],
        metadata={
            "benchmark_setting": "V-REPLICATION-ROBUSTNESS",
            "cohort": "heldout",
            "evidence_scope": "real_trained_game",
            "independent_block": "VHO-fixture",
            "source_id": "openml-fixture",
            "replicated_owner": "a",
            "replication_factor": 2,
            "replication_group_id": "VREP-test-a",
            "primary_metric_eligible": True,
        },
    )
    config = BenchmarkConfig(
        name="axis-metadata",
        output_dir="unused",
        seeds=(0,),
        methods={"valuation": {"random": {}}, "procurement": {}, "trading": {}},
        case_ids={"valuation": (case.case_id,), "procurement": (), "trading": ()},
        strategic_audit=False,
    )

    (result,) = run_benchmark(
        config,
        cases={"valuation": (case,), "procurement": (), "trading": ()},
    )

    assert result.metadata["replicated_owner"] == "a"
    assert result.metadata["replication_factor"] == 2
    assert result.metadata["replication_group_id"] == "VREP-test-a"
    assert result.metadata["primary_metric_eligible"] is True
    assert result.metadata["cohort"] == "heldout"
    assert result.metadata["evidence_scope"] == "real_trained_game"
    assert result.metadata["independent_block"] == "VHO-fixture"
    assert result.metadata["source_id"] == "openml-fixture"


def test_runner_can_freeze_scientific_metric_and_diagnostic_surface() -> None:
    case = next(
        case
        for case in build_cases()["procurement"]
        if case.case_id == "PADD-independent-b30"
    )
    config = BenchmarkConfig(
        name="frozen-result-contract",
        output_dir="unused",
        seeds=(0,),
        methods={
            "valuation": {},
            "procurement": {"budget_optimum": {}, "cgl_deterministic": {}},
            "trading": {},
        },
        case_ids={"valuation": (), "procurement": (case.case_id,), "trading": ()},
        strategic_audit=False,
        result_metric_ids={
            "valuation": (),
            "procurement": ("oracle_ratio",),
            "trading": (),
        },
        result_diagnostic_keys=(),
    )

    results = run_benchmark(
        config,
        cases={"valuation": (), "procurement": (case,), "trading": ()},
    )
    cgl = next(row for row in results if row.method_id == "cgl_deterministic")

    assert set(cgl.metrics) == {"oracle_ratio"}
    assert "mechanism_branch" not in cgl.metadata


def test_generic_reports_write_three_tracks_and_na_reasons(tmp_path):
    config = BenchmarkConfig(
        name="report",
        output_dir=str(tmp_path),
        seeds=(0,),
        methods={"valuation": {"random": {}}, "procurement": {}, "trading": {}},
        case_ids={"valuation": ("C-add",), "procurement": (), "trading": ()},
    )
    results = run_benchmark(config)
    raw = write_jsonl(results, tmp_path / "raw_results.jsonl")
    csvs = write_track_csvs(results, tmp_path)
    report = write_markdown_report(results, tmp_path / "report.md")

    assert raw.stat().st_size > 0
    assert {path.name for path in csvs} == {
        "summary_valuation.csv",
        "summary_procurement.csv",
        "summary_trading.csv",
    }
    assert all(path.stat().st_size > 0 for path in csvs)
    text = report.read_text(encoding="utf-8")
    assert "Coverage summary" in text
    assert "families" in text
    assert "N/A" in text
    assert "missing_oracle_output" in text


def test_jsonl_results_round_trip_metric_values(tmp_path):
    config = BenchmarkConfig(
        name="round-trip",
        output_dir=str(tmp_path),
        seeds=(0,),
        methods={"valuation": {"random": {}}, "procurement": {}, "trading": {}},
        case_ids={"valuation": ("C-add",), "procurement": (), "trading": ()},
    )
    original = run_benchmark(config)
    path = write_jsonl(original, tmp_path / "raw_results.jsonl")

    loaded = load_jsonl_results(path)

    assert [row.to_dict() for row in loaded] == [row.to_dict() for row in original]


def test_jsonl_loader_keeps_legacy_schema_1_1_result_without_outcome(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(
        '{"run_id":"legacy","track":"valuation","method_id":"m",'
        '"case_id":"c","seed":0,"status":"completed","metrics":{},'
        '"runtime_seconds":0.0,"schema_version":"1.1"}\n',
        encoding="utf-8",
    )

    (loaded,) = load_jsonl_results(path)

    assert loaded.schema_version == "1.1"
    assert loaded.outcome is None
