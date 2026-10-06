from __future__ import annotations

from pathlib import Path

import pytest
from datamechbench.expectations import load_metric_definitions


def test_repository_metrics_have_decision_guidance() -> None:
    metrics = load_metric_definitions()

    assert metrics
    for metric in metrics.values():
        assert metric.display_name
        assert metric.question_answered.endswith("?")
        assert metric.interpretation
        assert metric.good_value
        assert metric.bad_value
        assert metric.applicability
        assert metric.failure_modes
        assert metric.ranking_role in {
            "primary",
            "guardrail",
            "diagnostic",
            "cost",
            "robustness",
            "decision_robustness",
            "decision_transfer_robustness",
            "admissibility_frontier",
            "admissibility_gate",
            "evidence_bottleneck_diagnostic",
        }
        assert metric.paper_protocol


def test_metric_catalog_rejects_unknown_companion(tmp_path: Path) -> None:
    catalog = tmp_path / "metrics.yaml"
    catalog.write_text(
        """schema_version: '2.0'
metrics:
  - metric_id: example
    track: valuation
    description: Example metric
    direction: maximize
    unit: ratio
    aggregation: macro_case_mean
    companion_metrics: [missing]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown companion metric.*missing"):
        load_metric_definitions(catalog)


def test_valid_range_is_ordered() -> None:
    for metric in load_metric_definitions().values():
        if metric.valid_range is not None:
            assert metric.valid_range[0] <= metric.valid_range[1]


def test_trading_loss_decomposition_metrics_are_explicit_and_noncomposite() -> None:
    metrics = load_metric_definitions()

    frontier = metrics["count_matched_frontier_gft_ratio"]
    capacity = metrics["capacity_loss_ratio"]
    selection = metrics["selection_pricing_loss_ratio"]

    assert frontier.formula == "GFT^*_{q(m,e)}/GFT^*"
    assert capacity.formula == "1-GFT^*_{q(m,e)}/GFT^*"
    assert selection.formula == "(GFT^*_{q(m,e)}-GFT(m,e))/GFT^*"
    assert capacity.ranking_role == "diagnostic"
    assert selection.ranking_role == "diagnostic"
    assert "capacity_loss_ratio" in selection.companion_metrics
    assert "selection_pricing_loss_ratio" in capacity.companion_metrics
