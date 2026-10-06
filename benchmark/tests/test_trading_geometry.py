from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

from datamechbench.settings import trading as trading_settings


def _efficient_trade_count(case) -> int:
    values = sorted(case.true_values.values(), reverse=True)
    costs = sorted(case.true_costs.values())
    return sum(value >= cost for value, cost in zip(values, costs, strict=True))


def _case_signature(case) -> str:
    return json.dumps(
        {
            "case_id": case.case_id,
            "values": {key: str(value) for key, value in case.true_values.items()},
            "costs": {key: str(value) for key, value in case.true_costs.items()},
            "metadata": dict(case.metadata),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def test_market_geometry_cases_freeze_factorial_contract() -> None:
    assert hasattr(trading_settings, "make_market_geometry_cases")
    cases = trading_settings.make_market_geometry_cases(seed=9)

    assert len(cases) == 9
    assert len({case.case_id for case in cases}) == 9
    assert {
        Decimal(str(case.metadata["minimum_efficient_surplus"])) for case in cases
    } == {Decimal("0.02"), Decimal("0.20"), Decimal("0.60")}
    assert {Decimal(str(case.metadata["buyer_margin_share"])) for case in cases} == {
        Decimal("0.20"),
        Decimal("0.50"),
        Decimal("0.80"),
    }
    assert all(case.metadata["benchmark_setting"] == "T-MARKET-GEOMETRY" for case in cases)
    assert all(case.metadata["geometry_study_version"] == "1.0" for case in cases)
    assert all(case.metadata["efficient_trade_count"] == 8 for case in cases)
    assert all(case.metadata["market_size"] == 16 for case in cases)
    assert all(case.metadata["crossing_price_anchor"] == 0.5 for case in cases)


def test_market_geometry_cases_hold_thickness_fixed_without_report_ties() -> None:
    cases = trading_settings.make_market_geometry_cases(seed=9)

    for case in cases:
        assert len(case.public.buyer_ids) == 16
        assert len(case.public.seller_ids) == 16
        assert _efficient_trade_count(case) == 8
        assert len(set(case.true_values.values())) == 16
        assert len(set(case.true_costs.values())) == 16
        assert set(case.true_values.values()).isdisjoint(case.true_costs.values())
        values = sorted(case.true_values.values(), reverse=True)
        costs = sorted(case.true_costs.values())
        assert values[7] - costs[7] == Decimal(
            str(case.metadata["minimum_efficient_surplus"])
        )
        assert values[8] < costs[8]


def test_market_geometry_cases_are_seed_invariant_and_byte_stable() -> None:
    first = trading_settings.make_market_geometry_cases(seed=9)
    repeated = trading_settings.make_market_geometry_cases(seed=9)
    different_seed = trading_settings.make_market_geometry_cases(seed=91)

    assert [_case_signature(case) for case in first] == [
        _case_signature(case) for case in repeated
    ]
    assert [_case_signature(case) for case in first] == [
        _case_signature(case) for case in different_seed
    ]


def test_geometry_runner_uses_one_deterministic_run_and_full_random_seed_panel() -> None:
    from datamechbench.trading_geometry import audit_geometry_runs, run_geometry_study

    rows = run_geometry_study(
        method_ids=("mcafee", "lottery_muda", "random_sampling_double"),
        seeds=(0, 1),
    )

    assert len(rows) == 45
    assert len({row.run_id for row in rows}) == 45
    assert {row.seed for row in rows if row.method_id == "mcafee"} == {0}
    assert {row.seed for row in rows if row.method_id == "lottery_muda"} == {0, 1}
    assert {row.seed for row in rows if row.method_id == "random_sampling_double"} == {
        0,
        1,
    }
    assert audit_geometry_runs(
        rows,
        method_ids=("mcafee", "lottery_muda", "random_sampling_double"),
        seeds=(0, 1),
    ) == ()


def test_geometry_runner_records_real_outcomes_and_partition_diagnostics() -> None:
    from datamechbench.trading_geometry import (
        decompose_trade_loss,
        run_geometry_study,
    )

    case = trading_settings.make_market_geometry_cases()[0]
    values = sorted(case.true_values.values(), reverse=True)
    costs = sorted(case.true_costs.values())
    surpluses = [float(value - cost) for value, cost in zip(values, costs, strict=True) if value >= cost]
    oracle = sum(surpluses)
    seven_trade_frontier = sum(surpluses[:7]) / oracle

    frontier, capacity_loss, selection_loss = decompose_trade_loss(
        case,
        trade_count=7,
        realized_gft_ratio=seven_trade_frontier - 0.125,
    )

    assert math.isclose(frontier, seven_trade_frontier, abs_tol=1e-12)
    assert math.isclose(capacity_loss, 1.0 - seven_trade_frontier, abs_tol=1e-12)
    assert math.isclose(selection_loss, 0.125, abs_tol=1e-12)
    assert math.isclose(capacity_loss + selection_loss, 1.0 - (seven_trade_frontier - 0.125), abs_tol=1e-12)

    rows = run_geometry_study(
        method_ids=("trade_reduction", "sbba", "lottery_muda"),
        seeds=(0, 1, 2),
    )

    assert rows
    for row in rows:
        assert 0.0 <= row.gain_from_trade_ratio <= 1.0
        assert 0.0 <= row.capacity_utilization <= 1.0
        assert math.isfinite(row.gain_from_trade_ratio)
        assert math.isfinite(row.capacity_utilization)
        assert 0.0 <= row.count_matched_frontier_gft_ratio <= 1.0
        assert 0.0 <= row.capacity_loss_ratio <= 1.0
        assert row.selection_pricing_loss_ratio >= -1e-12
        assert math.isclose(
            row.capacity_loss_ratio + row.selection_pricing_loss_ratio,
            1.0 - row.gain_from_trade_ratio,
            abs_tol=1e-12,
        )
        assert row.individual_rationality is True
        assert row.weak_budget_balance is True
    trade_reduction = [row for row in rows if row.method_id == "trade_reduction"]
    assert trade_reduction
    assert max(abs(row.selection_pricing_loss_ratio) for row in trade_reduction) < 1e-12
    split_rows = [row for row in rows if row.method_id == "lottery_muda"]
    assert split_rows
    assert all(row.efficient_partition_imbalance is not None for row in split_rows)
    assert all(0.0 <= row.efficient_partition_imbalance <= 1.0 for row in split_rows)
    assert all(row.left_price_available is not None for row in split_rows)
    assert all(row.right_price_available is not None for row in split_rows)
    assert all(row.normalized_cross_price_gap is not None for row in split_rows)
    assert all(row.efficient_partition_imbalance is None for row in rows if row.method_id == "sbba")


def test_geometry_audit_rejects_missing_duplicate_and_nonfinite_runs() -> None:
    from dataclasses import replace

    from datamechbench.trading_geometry import audit_geometry_runs, run_geometry_study

    methods = ("mcafee", "lottery_muda")
    rows = run_geometry_study(method_ids=methods, seeds=(0, 1))

    missing = audit_geometry_runs(rows[:-1], method_ids=methods, seeds=(0, 1))
    assert any(error.startswith("missing_run:") for error in missing)

    duplicate = audit_geometry_runs((*rows, rows[0]), method_ids=methods, seeds=(0, 1))
    assert duplicate == (f"duplicate_run_id:{rows[0].run_id}",)

    nonfinite_rows = list(rows)
    nonfinite_rows[0] = replace(nonfinite_rows[0], gain_from_trade_ratio=float("nan"))
    nonfinite = audit_geometry_runs(nonfinite_rows, method_ids=methods, seeds=(0, 1))
    assert nonfinite == (f"nonfinite_gain_from_trade_ratio:{rows[0].run_id}",)


def test_geometry_summaries_keep_mechanism_randomness_conditional_on_each_cell() -> None:
    from datamechbench.trading_geometry import (
        run_geometry_study,
        summarize_geometry_cells,
        summarize_geometry_methods,
    )

    rows = run_geometry_study(
        method_ids=("mcafee", "lottery_muda"), seeds=(0, 1, 2, 3)
    )
    cells = summarize_geometry_cells(rows)
    methods = summarize_geometry_methods(cells, rows)

    assert len(cells) == 18
    assert {cell.run_count for cell in cells if cell.method_id == "mcafee"} == {1}
    assert {cell.run_count for cell in cells if cell.method_id == "lottery_muda"} == {4}
    assert all(cell.randomness_estimand == "deterministic_point" for cell in cells if cell.method_id == "mcafee")
    assert all(
        cell.randomness_estimand == "conditional_expectation_over_mechanism_seed"
        for cell in cells
        if cell.method_id == "lottery_muda"
    )
    assert all(cell.imbalance_gft_spearman is None for cell in cells if cell.method_id == "mcafee")
    assert {method.cell_count for method in methods} == {9}
    assert {method.method_id for method in methods} == {"mcafee", "lottery_muda"}
    assert all(0.0 <= method.worst_expected_gft <= method.macro_expected_gft <= 1.0 for method in methods)


def test_geometry_effects_require_same_seed_panels_and_preserve_seed_semantics() -> None:
    from datamechbench.trading_geometry import (
        paired_geometry_effects,
        run_geometry_study,
    )

    rows = run_geometry_study(
        method_ids=("trade_reduction", "vickrey_muda"), seeds=(0, 1, 2, 3)
    )
    effects = paired_geometry_effects(rows)

    assert len(effects) == 12
    assert {effect.run_count for effect in effects if effect.method_id == "trade_reduction"} == {1}
    assert {effect.run_count for effect in effects if effect.method_id == "vickrey_muda"} == {4}
    assert all(effect.reference_buyer_margin_share == 0.5 for effect in effects)
    assert all(effect.comparison_buyer_margin_share in {0.2, 0.8} for effect in effects)
    assert all(effect.interval_scope == "mechanism_randomness_not_market_sampling" for effect in effects)

    unmatched = tuple(
        row
        for row in rows
        if not (
            row.method_id == "vickrey_muda"
            and row.minimum_efficient_surplus == 0.02
            and row.buyer_margin_share == 0.8
            and row.seed == 3
        )
    )
    try:
        paired_geometry_effects(unmatched)
    except ValueError as error:
        assert str(error).startswith("unmatched_seed_panel:")
    else:
        raise AssertionError("unmatched seed panel must fail closed")


def _artifact_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def test_geometry_artifacts_rebuild_byte_identically_and_detect_tampering(tmp_path) -> None:
    from datamechbench.trading_geometry import (
        build_geometry_artifacts,
        verify_geometry_artifacts,
    )

    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "method_ids": ("mcafee", "lottery_muda"),
        "seeds": (0, 1, 2, 3),
    }
    built = build_geometry_artifacts(first, **kwargs)
    build_geometry_artifacts(second, **kwargs)

    assert built["valid"] is True
    assert built["raw_run_count"] == 45
    assert built["cell_count"] == 18
    assert built["method_count"] == 2
    assert built["effect_count"] == 12
    assert built["inference_unit"] == "controlled_geometry_cell"
    assert built["seed_semantics"] == "mechanism_randomness_conditional_on_cell"
    assert _artifact_bytes(first) == _artifact_bytes(second)
    assert verify_geometry_artifacts(first / "manifest.json") == {
        "errors": [],
        "valid": True,
    }

    raw = first / "raw_runs.jsonl"
    raw.write_text(raw.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    checked = verify_geometry_artifacts(first / "manifest.json")
    assert checked["valid"] is False
    assert checked["errors"] == ["sha256_mismatch:raw_runs.jsonl"]


def test_geometry_artifacts_encode_multilayer_findings_without_market_overclaim(tmp_path) -> None:
    from datamechbench.trading_geometry import build_geometry_artifacts

    build_geometry_artifacts(tmp_path)
    findings = json.loads((tmp_path / "findings.json").read_text(encoding="utf-8"))

    assert findings["evidence_tier"] == "exploratory_controlled_stress"
    assert findings["independent_market_count"] == 0
    assert findings["mechanism_seed_count"] == 128
    assert {item["finding_id"] for item in findings["findings"]} == {
        "fixed_thickness_does_not_fix_geometry_response",
        "partition_imbalance_tracks_random_halving_loss",
        "capacity_does_not_identify_selection_quality",
    }
    fixed = next(
        item
        for item in findings["findings"]
        if item["finding_id"] == "fixed_thickness_does_not_fix_geometry_response"
    )
    assert fixed["efficient_trade_count"] == 8
    assert fixed["trade_reduction_geometry_range"] < 0.01
    assert fixed["largest_other_geometry_range"] > 0.20
    partition = next(
        item
        for item in findings["findings"]
        if item["finding_id"] == "partition_imbalance_tracks_random_halving_loss"
    )
    assert partition["maximum_residual_partition_spearman"] < -0.90
    assert partition["least_negative_residual_partition_spearman"] < -0.80
    capacity = next(
        item
        for item in findings["findings"]
        if item["finding_id"] == "capacity_does_not_identify_selection_quality"
    )
    assert capacity["capacity_utilization_difference"] == 0.0
    assert capacity["vickrey_minus_lottery_macro_gft"] > 0.02
    assert capacity["lottery_minus_vickrey_selection_pricing_loss"] > 0.02
    assert capacity["trade_reduction_max_selection_pricing_loss"] < 1e-12
    assert capacity["vickrey_minus_lottery_geometry_range"] > 0.09
    assert all(item["claim_scope"] == "controlled_cells_only" for item in findings["findings"])
