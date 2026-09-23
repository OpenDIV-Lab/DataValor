from __future__ import annotations

import pytest


def test_input_parser_normalizes_structured_text_and_infers_schema():
    from UI.services.input_parsing import parse_input

    json_preview = parse_input("json", '[{"id": 1, "active": true}, {"id": 2, "active": false}]')
    assert json_preview.records[1] == {"id": 2, "active": False}
    assert json_preview.schema == {"id": "integer", "active": "boolean"}
    assert json_preview.errors == ()

    jsonl_preview = parse_input("jsonl", '{"id":1}\n{"id":2}\n')
    assert [row["id"] for row in jsonl_preview.records] == [1, 2]

    csv_preview = parse_input("csv", 'name,amount\n"north,west",12.5\neast,9\n')
    assert csv_preview.records[0] == {"name": "north,west", "amount": 12.5}
    assert csv_preview.schema == {"name": "string", "amount": "number"}

    tsv_preview = parse_input("tsv", "name\tcount\na\t3\n")
    assert tsv_preview.records == ({"name": "a", "count": 3},)


def test_input_parser_supports_key_values_overrides_and_localized_errors():
    from UI.services.input_parsing import parse_input

    preview = parse_input(
        "key_value",
        {"threshold": "0.8", "enabled": "true"},
        {"schema": {"threshold": "number", "enabled": "boolean"}},
    )
    assert preview.records == ({"threshold": 0.8, "enabled": True},)
    assert preview.schema["threshold"] == "number"

    malformed = parse_input("jsonl", '{"id": 1}\nnot-json')
    assert malformed.records == ({"id": 1},)
    assert malformed.errors[0].location == "line:2"
    assert malformed.errors[0].code == "invalid_json"

    uneven = parse_input("csv", "a,b\n1,2,3\n")
    assert uneven.errors[0].location == "row:2"
    assert uneven.errors[0].code == "column_count"


def test_input_options_and_reference_validation_are_effective():
    from UI.services.input_parsing import parse_input

    sampled = parse_input("csv", "id\n1\n2\n3\n", {"sample_size": 2, "batch_size": 1, "encoding": "utf-8"})
    assert len(sampled.records) == 2
    assert sampled.stats["sampled"] is True
    assert sampled.stats["batch_count"] == 2

    invalid_boolean = parse_input("key_value", {"enabled": "maybe"}, {"schema": {"enabled": "boolean"}})
    assert invalid_boolean.errors[0].code == "schema_coercion"
    assert invalid_boolean.stats["valid"] is False

    missing = parse_input("catalog", "catalog://missing", {"available_references": ["known"]})
    assert missing.errors[0].code == "missing_reference"
    known = parse_input("catalog", "catalog://known", {"available_references": ["known"]})
    assert known.errors == ()

    bad_encoding = parse_input("csv", "id\n1", {"encoding": "made-up"})
    assert bad_encoding.errors[0].code == "invalid_encoding"


def test_input_preview_route_is_registered():
    from UI.server.app import create_app

    paths = {route.path for route in create_app().routes}
    assert "/api/inputs/preview" in paths


def test_pricing_schema_exposes_concrete_model_specific_fields():
    from UI.services.pricing_workbench import pricing_schema

    schema = pricing_schema()
    expected = {
        "pricing.cost_plus",
        "pricing.value_based",
        "pricing.usage_based",
        "pricing.quality_freshness",
        "pricing.tiered_usage",
        "pricing.subscription",
        "pricing.risk_adjusted",
        "pricing.price_range",
        "pricing.comparable",
        "pricing.rights_differentiated",
        "pricing.freshness_tier",
        "pricing.version_delta",
        "pricing.expected_revenue",
    }
    assert expected <= schema.keys()
    assert all(model["fields"] for model in schema.values())
    assert schema["pricing.subscription"]["fields"][0]["key"] == "period_fee"
    assert any(field["key"] == "candidate_prices" for field in schema["pricing.expected_revenue"]["fields"])


def test_pricing_execution_contains_attributable_trace_and_keeps_old_shape():
    from UI.services.operations import execute

    payload = {
        "product_id": "licensed-data",
        "title": "Licensed data",
        "owner_id": "seller-a",
        "data": {"uri": "memory://licensed", "format": "records", "record_count": 2},
        "rights": {"purposes": ["analytics"], "commercial_use": True},
        "records": [{"value": 1}, {"value": 2}],
    }
    result, producer = execute(
        "pricing",
        payload,
        {"model": "pricing.subscription", "period_fee": 1000, "included_usage": 1, "usage": 3, "overage_unit_price": 50},
        "pricing-trace-run",
    )
    assert producer == "pricing.subscription"
    assert result["price"]["amount"] == "1100.00"
    assert result["trace"][0]["step"] == "normalize_parameters"
    assert result["trace"][-1]["step"] == "quote"
    assert result["normalized_parameters"]["usage"] == 3


def test_every_exposed_pricing_model_executes_with_its_ui_defaults():
    from datavalor.core import RunContext
    from UI.services.catalog import product_from_payload
    from UI.services.pricing_workbench import pricing_schema, run_pricing

    product = product_from_payload(
        {
            "product_id": "default-priced",
            "title": "Default priced",
            "owner_id": "seller",
            "data": {"uri": "memory://default", "format": "records"},
            "rights": {"commercial_use": True, "purposes": ["analytics"]},
        }
    )
    for model in pricing_schema():
        quote, _, trace, producer = run_pricing(product, {"model": model}, RunContext(f"run-{model}"), record_count=10)
        assert producer == model
        assert quote.price.amount >= 0
        assert trace[-1]["step"] == "quote"


def test_workbench_schema_route_is_registered():
    from UI.server.app import create_app

    paths = {route.path for route in create_app().routes}
    assert "/api/workbench/schemas" in paths


def _market_products():
    from UI.services.catalog import product_from_payload

    def payload(product_id, owner, quality):
        return {
            "product_id": product_id,
            "title": product_id,
            "owner_id": owner,
            "data": {"uri": f"memory://{product_id}", "format": "records"},
            "rights": {"purposes": ["analytics"], "commercial_use": True},
            "metadata": {"quality": quality, "freshness": 0.9, "group": "retail"},
            "records": [],
        }

    return (product_from_payload(payload("demand", "seller-a", 0.9)), product_from_payload(payload("weather", "seller-b", 0.8)))


def test_market_schema_and_multi_product_bundle_analysis_are_real():
    from datavalor.core import RunContext
    from UI.services.market_workbench import market_schema, run_market

    schema = market_schema()
    assert {"multi_unit_uniform_price", "quality_aware_procurement", "bundle_matching"} <= schema["mechanisms"].keys()
    result, producer = run_market(
        _market_products(),
        {
            "mechanism": "bundle_matching",
            "currency": "CNY",
            "budget": 200,
            "bids": [{"buyer_id": "buyer-a", "product_ids": ["demand", "weather"], "amount": 180, "constraints": {"bundle_mode": "and"}}],
            "asks": [
                {"seller_id": "seller-a", "product_ids": ["demand"], "reserve": 60, "metadata": {"quality": 0.9}},
                {"seller_id": "seller-b", "product_ids": ["weather"], "reserve": 50, "metadata": {"quality": 0.8}},
            ],
        },
        RunContext("bundle-run"),
    )
    assert producer == "bundle_matching"
    assert result["bundle_selection"].matches[0].product_ids == ("demand", "weather")
    assert result["bundle_selection"].total_cost.amount == 110
    assert result["market_health"].metrics["active_listings"] == 2
    assert result["trace"][-1]["step"] == "diagnostics"


def test_advanced_market_mechanism_executes_multi_unit_and_rejects_invalid_orders():
    from datavalor.core import RunContext
    from UI.services.market_workbench import run_market

    products = _market_products()
    result, producer = run_market(
        products,
        {
            "mechanism": "multi_unit_uniform_price",
            "bids": [
                {"buyer_id": "a", "product_ids": ["demand"], "amount": 100, "quantity": 2},
                {"buyer_id": "b", "product_ids": ["demand"], "amount": 80, "quantity": 2},
            ],
            "asks": [{"seller_id": "seller-a", "product_ids": ["demand"], "reserve": 50, "quantity": 3}],
            "supply": {"demand": 3},
        },
        RunContext("multi-run"),
    )
    assert producer == "multi_unit_uniform_price"
    assert result["outcome"].diagnostics["allocated"] == "3"
    assert len(result["demand_segments"]) >= 1
    assert result["audit"]["status"] == "valid"

    with pytest.raises(ValueError, match="unknown product"):
        run_market(products, {"bids": [{"buyer_id": "x", "product_ids": ["missing"], "amount": 1}], "asks": []}, RunContext("bad-product"))
    with pytest.raises(ValueError, match="non-negative"):
        run_market(products, {"bids": [{"buyer_id": "x", "product_ids": ["demand"], "amount": 1, "quantity": -1}], "asks": []}, RunContext("bad-quantity"))
    with pytest.raises(ValueError, match="single currency"):
        run_market(products, {"bids": [{"buyer_id": "x", "product_ids": ["demand"], "amount": 1, "currency": "USD"}], "asks": [{"seller_id": "s", "product_ids": ["demand"], "reserve": 1, "currency": "CNY"}]}, RunContext("bad-currency"))


def test_market_rejects_cross_product_and_invalid_market_level_configuration():
    from datavalor.core import RunContext
    from UI.services.market_workbench import run_market

    products = _market_products()
    with pytest.raises(ValueError, match="same single product"):
        run_market(products, {"mechanism": "mcafee_double_auction", "bids": [{"buyer_id": "b", "product_ids": ["demand"], "amount": 100}], "asks": [{"seller_id": "s", "product_ids": ["weather"], "reserve": 10}]}, RunContext("cross-product"))
    with pytest.raises(ValueError, match="budget must be non-negative"):
        run_market(products, {"mechanism": "budget_aware_procurement", "budget": -1, "asks": [{"seller_id": "s", "product_ids": ["demand"], "reserve": 1}]}, RunContext("negative-budget"))
    with pytest.raises(ValueError, match="requires at least one"):
        run_market(products, {"mechanism": "mcafee_double_auction", "bids": [], "asks": []}, RunContext("empty-book"))
    with pytest.raises(ValueError, match="unknown supply product"):
        run_market(products, {"mechanism": "multi_unit_uniform_price", "supply": {"missing": 1}, "bids": [{"buyer_id": "b", "product_ids": ["demand"], "amount": 2}], "asks": [{"seller_id": "s", "product_ids": ["demand"], "reserve": 1}]}, RunContext("bad-supply"))


def test_operation_payload_validates_product_ids():
    from pydantic import ValidationError

    from UI.server.app import OperationPayload

    with pytest.raises(ValidationError):
        OperationPayload(product_id="../escape")
    with pytest.raises(ValidationError):
        OperationPayload(product_ids=["valid", "bad/id"])


def test_complex_ui_stays_inside_existing_modules_and_renders_real_controls():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "UI" / "index.html").read_text()
    script = (root / "UI" / "workbench-complex.js").read_text()
    assert html.count('class="nav"') + html.count('class="nav active"') == 13
    assert 'workbench-complex.js' in html
    assert 'workbench-complex.css' in html
    for input_type in ("json", "jsonl", "csv", "tsv", "key_value", "uri", "catalog", "artifact", "upstream"):
        assert input_type in script
    for tab in ("场景", "产品与输入", "参与方与订单", "定价合同", "市场机制", "执行过程", "结果与诊断"):
        assert tab in script
    assert "/inputs/preview" in script
    assert "/workbench/schemas" in script
    assert "product_ids" in script
    assert "normalized_parameters" in script
    assert "trace" in script
    assert "escapeAttribute" in script
    assert "execution_mode" in script
    assert "renderFailureTrace" in script
    assert "/operations/" in script
