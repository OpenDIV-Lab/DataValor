from __future__ import annotations

from pathlib import Path

import pytest
from datamechbench.expectations import (
    ExpectationSpec,
    evaluate_expectations,
    load_expectations,
    load_metric_definitions,
)
from datamechbench.models import BenchmarkResult


def _result(
    value: object,
    *,
    status: str = "completed",
    method_id: str = "mcafee",
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id="run",
        track="trading",
        method_id=method_id,
        case_id="case",
        seed=0,
        status=status,
        metrics={"weak_budget_balance": value},
        runtime_seconds=0.1,
        metadata={"method_family": "mcafee", "benchmark_setting": "T-DOUBLE"},
    )


def _claim(**overrides) -> ExpectationSpec:
    values = {
        "expectation_id": "mcafee-wbb",
        "family_id": "mcafee",
        "setting": "T-DOUBLE",
        "metric_id": "weak_budget_balance",
        "claim_kind": "theorem",
        "relation": "eq",
        "target": True,
        "tolerance": 0.0,
        "required_assumptions": ("independent_private_values",),
        "reference_key": "mcafee_double_auction",
        "claim_location": "Theorem 1",
    }
    values.update(overrides)
    return ExpectationSpec(**values)


def test_metric_loader_rejects_invalid_direction(tmp_path: Path) -> None:
    path = tmp_path / "metrics.yaml"
    path.write_text(
        """schema_version: '1.0'
metrics:
  - metric_id: bad
    track: valuation
    description: bad metric
    direction: sideways
    unit: ratio
    aggregation: macro_case_mean
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="direction"):
        load_metric_definitions(path)


@pytest.mark.parametrize(
    ("relation", "target", "observed", "expected_status"),
    [
        ("eq", 1.0, 1.0000001, "met"),
        ("le", 1.0, 1.2, "not_met"),
        ("ge", 0.9, 0.95, "met"),
        ("range", (0.0, 1.0), 1.2, "not_met"),
    ],
)
def test_claim_relations(
    relation: str, target: object, observed: float, expected_status: str
) -> None:
    result = _result(observed)
    claim = _claim(relation=relation, target=target, tolerance=1e-5)

    evaluated = evaluate_expectations(
        result, {"assumptions": ["independent_private_values"]}, (claim,)
    )

    assert evaluated[0].status == expected_status
    assert evaluated[0].observed == observed


def test_relative_claim_uses_declared_comparison_metric() -> None:
    claim = _claim(
        relation="relative_ge",
        target=None,
        comparison_family_id="vcg",
    )

    evaluated = evaluate_expectations(
        _result(0.8),
        {
            "assumptions": ["independent_private_values"],
            "comparison_metrics": {"vcg": {"weak_budget_balance": 0.7}},
        },
        (claim,),
    )

    assert evaluated[0].status == "met"
    assert evaluated[0].comparison_observed == 0.7


def test_unmet_assumptions_are_not_reported_as_failed_claim() -> None:
    evaluated = evaluate_expectations(_result(False), {"assumptions": []}, (_claim(),))

    assert evaluated[0].status == "assumptions_unmet"
    assert evaluated[0].missing_assumptions == ("independent_private_values",)


def test_missing_or_inapplicable_metric_is_not_applicable() -> None:
    result = _result({"value": None, "applicable": False, "reason": "no payments"})

    evaluated = evaluate_expectations(
        result, {"assumptions": ["independent_private_values"]}, (_claim(),)
    )

    assert evaluated[0].status == "not_applicable"
    assert evaluated[0].reason == "no payments"


def test_claim_violation_preserves_completed_result() -> None:
    result = _result(False)

    evaluated = evaluate_expectations(
        result, {"assumptions": ["independent_private_values"]}, (_claim(),)
    )

    assert evaluated[0].status == "not_met"
    assert result.status == "completed"
    assert result.metrics["weak_budget_balance"] is False


def test_method_scoped_claim_only_applies_to_named_variant() -> None:
    claim = _claim(method_id="mcafee_variant_a")

    named = evaluate_expectations(
        _result(True, method_id="mcafee_variant_a"),
        {"assumptions": ["independent_private_values"]},
        (claim,),
    )
    sibling = evaluate_expectations(
        _result(True, method_id="mcafee_variant_b"),
        {"assumptions": ["independent_private_values"]},
        (claim,),
    )

    assert named[0].status == "met"
    assert sibling == ()


def test_default_expectation_catalog_references_known_metrics() -> None:
    metrics = load_metric_definitions()
    expectations = load_expectations()

    assert expectations
    assert {item.metric_id for item in expectations} <= set(metrics)
    assert all(item.claim_location for item in expectations)
