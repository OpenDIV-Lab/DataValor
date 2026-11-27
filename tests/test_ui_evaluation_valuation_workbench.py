from __future__ import annotations

import pytest

from datavalor.core import RunContext
from UI.services.catalog import product_from_payload


def _product(records: list[dict] | None = None):
    payload = {
        "product_id": "asset-a",
        "title": "Asset A",
        "owner_id": "seller-a",
        "data": {"uri": "memory://asset-a", "format": "records", "record_count": len(records or ())},
        "rights": {"purposes": ["analytics"], "commercial_use": True},
        "metadata": {},
        "records": records or [],
    }
    return payload, product_from_payload(payload)


def test_evaluation_schema_exposes_datavalor_metrics_by_modality():
    from UI.services.evaluation_workbench import evaluation_schema

    schema = evaluation_schema()

    assert set(schema["modalities"]) == {"tabular", "text", "image", "audio", "video", "multimodal"}
    assert "tabular.outlier_rate" in {item["name"] for item in schema["modalities"]["tabular"]["metrics"]}
    assert "text.lexical_diversity" in {item["name"] for item in schema["modalities"]["text"]["metrics"]}
    assert "image.pixel_validity" in {item["name"] for item in schema["modalities"]["image"]["metrics"]}
    assert "audio.clipping_rate" in {item["name"] for item in schema["modalities"]["audio"]["metrics"]}
    assert "video.privacy_cv" in {item["name"] for item in schema["modalities"]["video"]["metrics"]}
    assert "multimodal.alignment" in {item["name"] for item in schema["modalities"]["multimodal"]["metrics"]}
    assert all(item["implementation"].startswith("datavalor.data_eval") for modality in schema["modalities"].values() for item in modality["metrics"])
    tabular = {item["name"]: item for item in schema["modalities"]["tabular"]["metrics"]}
    assert tabular["basic.completeness"]["implementation"] == "datavalor.data_eval.CompletenessMetric"
    assert tabular["tabular.outlier_rate"]["implementation"] == "datavalor.data_eval.TabularOutlierRateMetric"


def test_evaluation_runs_only_selected_metrics_with_modality_parameters():
    from UI.services.evaluation_workbench import run_evaluation

    payload, product = _product([
        {"text": "useful diverse training sentence", "lang": "zh"},
        {"text": "useful repeated repeated sentence", "lang": "zh"},
    ])
    report, producer = run_evaluation(
        product,
        payload["records"],
        {
            "modality": "text",
            "metrics": ["text.length_quality", "text.lexical_diversity"],
            "text_field": "text",
            "min_tokens": 2,
            "max_tokens": 20,
        },
        RunContext("evaluation-text"),
    )

    assert producer == "basic.composite_evaluator"
    assert [metric.name for metric in report.metrics] == ["text.length_quality", "text.lexical_diversity"]
    assert report.diagnostics["modality"] == "text"
    assert report.diagnostics["selected_metrics"] == ("text.length_quality", "text.lexical_diversity")


def test_evaluation_rejects_metric_from_another_modality():
    from UI.services.evaluation_workbench import run_evaluation

    payload, product = _product([{"text": "hello"}])
    with pytest.raises(ValueError, match="not available for text"):
        run_evaluation(
            product,
            payload["records"],
            {"modality": "text", "metrics": ["image.pixel_validity"]},
            RunContext("bad-metric"),
        )


def test_batch_quality_summary_respects_metric_direction_and_skips_descriptive_values():
    from UI.services.batches import _extract_metrics

    metrics = {}
    _extract_metrics(
        "evaluation",
        {"metrics": [
            {"value": 0.8, "direction": "higher_is_better"},
            {"value": 0.1, "direction": "lower_is_better"},
            {"value": 42, "direction": "descriptive"},
        ]},
        metrics,
    )

    assert metrics["quality_score"] == 0.85


def test_valuation_schema_exposes_existing_datavalor_valuators():
    from UI.services.valuation_workbench import valuation_schema

    schema = valuation_schema()
    methods = schema["methods"]

    assert {
        "valuation.weighted_user_task",
        "valuation.quality_adjusted",
        "valuation.scenario",
        "valuation.risk_adjusted",
        "valuation.counterfactual",
        "valuation.symbolic",
        "valuation.market_context",
        "valuation.scarcity_adjusted",
        "valuation.incremental_coverage",
        "valuation.substitution_adjusted",
        "valuation.time_decay",
        "valuation.update_stream",
    } <= methods.keys()
    assert all(item["implementation"].startswith("datavalor.data_value") for item in methods.values())


@pytest.mark.parametrize(
    ("method", "parameters"),
    [
        ("valuation.weighted_user_task", {"evaluation_vector": {"quality": 0.8, "task_utility": 0.7}}),
        ("valuation.quality_adjusted", {"evaluation_vector": {"quality": 0.8, "freshness": 0.9}}),
        ("valuation.scenario", {"evaluation_vector": {"quality": 0.8, "freshness": 0.9}}),
        ("valuation.risk_adjusted", {"evaluation_vector": {"quality": 0.8}, "uncertainty": {"std_error": 0.05}}),
        ("valuation.counterfactual", {"evaluation_vector": {"accuracy": 0.9}, "baseline_vector": {"accuracy": 0.7}}),
        ("valuation.symbolic", {"evaluation_vector": {"quality": 0.8}, "expression": "base_value * quality"}),
        ("valuation.market_context", {"market_factors": {"quality": 0.8, "demand_fit": 0.9, "freshness": 0.9}}),
        ("valuation.scarcity_adjusted", {"scarcity": 0.7, "task_relevance": 0.9}),
        ("valuation.incremental_coverage", {"incremental_coverage": 0.6, "quality": 0.9, "task_relevance": 0.8}),
        ("valuation.substitution_adjusted", {"substitutes": [{"coverage": 0.2, "quality_ratio": 0.8}]}),
        ("valuation.time_decay", {"age_days": 10, "half_life_days": 30, "time_sensitivity": 0.8}),
        ("valuation.update_stream", {"updates": [{"period": 0, "marginal_value": 300}, {"period": 1, "marginal_value": 200}], "discount_rate": 0.05}),
    ],
)
def test_every_exposed_valuation_method_executes(method, parameters):
    from UI.services.valuation_workbench import run_valuation

    _, product = _product([{"value": 1}])
    report, producer = run_valuation(
        product,
        {"method": method, "base_value": 1000, "currency": "CNY", **parameters},
        RunContext(f"run-{method}"),
    )

    assert producer == method
    assert report.method == method
    assert report.estimates
    assert all(estimate.value >= 0 for estimate in report.estimates)


def test_workbench_schema_route_includes_evaluation_and_valuation(tmp_path):
    from UI.server.app import create_app

    app = create_app(tmp_path)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/workbench/schemas")
    data = endpoint()["data"]

    assert set(data) == {"evaluation", "valuation", "pricing", "market"}
    assert data["evaluation"]["modalities"]["audio"]["label"] == "音频"
    assert data["valuation"]["methods"]["valuation.time_decay"]["label"] == "时间衰减估值"


def test_ui_renders_dynamic_modality_metrics_and_valuation_methods():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "UI" / "app.js").read_text()

    assert "operationFields(operation, parameters)" in script
    assert 'field.type === "checkbox_group"' in script
    assert "evaluation.modality" in script
    assert "valuation.method" in script
