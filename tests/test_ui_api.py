from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from UI.server.app import create_app
from UI.services.catalog import product_from_payload
from UI.services.components import component_catalog
from UI.services.operations import execute
from UI.services.workspace import Workspace


def product_payload(product_id="retail-demand"):
    return {
        "product_id": product_id,
        "title": "Retail demand",
        "owner_id": "seller-a",
        "version": "1",
        "data": {"uri": "memory://retail", "format": "records", "record_count": 2},
        "rights": {"purposes": ["analytics"], "commercial_use": True},
        "records": [{"region": "east", "sales": 12}, {"region": "west", "sales": 18}],
    }


def test_app_registers_workbench_routes_and_real_components(tmp_path):
    app = create_app(tmp_path)
    paths = {route.path for route in app.routes}
    assert {"/api/health", "/api/components", "/api/products", "/api/operations/{operation}", "/api/dashboard"} <= paths

    names = {item["name"] for item in component_catalog()}
    assert "basic.data_profiler" in names
    assert "valuation.market_context" in names
    assert "pricing.expected_revenue" in names


def test_workspace_product_crud_persists_and_rejects_unsafe_id(tmp_path):
    workspace = Workspace(tmp_path)
    payload = product_payload()
    workspace.put("products", payload["product_id"], payload)
    assert workspace.get("products", payload["product_id"])["title"] == "Retail demand"
    assert workspace.list("products")[0]["product_id"] == "retail-demand"
    payload["version"] = "2"
    workspace.put("products", payload["product_id"], payload)
    assert workspace.get("products", payload["product_id"])["version"] == "2"
    with pytest.raises(ValueError, match="only letters"):
        workspace.put("products", "../escape", payload)


def test_product_adapter_preserves_rights_and_reference():
    product = product_from_payload(product_payload())
    assert product.product_id == "retail-demand"
    assert product.data.record_count == 2
    assert product.rights.purposes == ("analytics",)


def test_real_profile_and_governance_operations():
    payload = product_payload("customers")
    payload["records"] = [{"email": "a@example.com", "age": 20}, {"email": "b@example.com", "age": None}]
    profile, profiler = execute("profile", payload, {}, "profile-run")
    assert profiler == "basic.data_profiler"
    assert profile["record_count"] == 2
    assert {item["name"] for item in profile["fields"]} == {"email", "age"}

    governance, policy = execute("governance", payload, {"operation": "analytics"}, "gov-run")
    assert policy == "rights.policy_evaluator"
    assert governance["decision"] == "allow"
    assert governance["security"]["scanned_fields"] == ["age", "email"]
    assert governance["security"]["findings"][0]["field_name"] == "email"

    evaluation, evaluator = execute("evaluation", payload, {"required_fields": ["email", "age"]}, "eval-run")
    assert evaluator == "basic.composite_evaluator"
    assert len(evaluation["metrics"]) == 3
    assert evaluation["summary"]["status"] == "succeeded"

    valuation, valuator = execute(
        "valuation",
        payload,
        {"base_value": 10000, "evaluation_vector": {"completeness": 0.75, "validity": 1.0}},
        "value-run",
    )
    assert valuator == "valuation.weighted_user_task"
    assert valuation["estimates"][0]["value"] == 8750.0


def test_component_catalog_has_actionable_metadata():
    components = component_catalog()
    assert len(components) > 20
    assert all({"name", "module", "kind", "version", "capabilities", "registry"} <= item.keys() for item in components)


def test_real_quote_and_market_operations_expose_repo_algorithms():
    payload = product_payload("market-data")
    quote, producer = execute(
        "pricing",
        payload,
        {
            "model": "pricing.quality_freshness",
            "base_price": 1000,
            "quality": 0.9,
            "freshness": 0.8,
            "quality_weight": 0.75,
        },
        "quote-run",
    )
    assert producer == "pricing.quality_freshness"
    assert quote["price"] == {"amount": "875.00", "currency": "CNY"}
    assert quote["components"]["factor"] == "0.875"

    optimized, producer = execute(
        "pricing",
        payload,
        {"model": "pricing.expected_revenue", "candidate_prices": [50, 100, 150]},
        "revenue-run",
    )
    assert producer == "pricing.expected_revenue"
    assert optimized["components"]["candidate_count"] == "3"

    market, mechanism = execute(
        "market",
        payload,
        {
            "mechanism": "second_price_auction",
            "bids": [
                {"buyer_id": "buyer-a", "amount": 1200, "budget": 1300},
                {"buyer_id": "buyer-b", "amount": 900, "budget": 1000},
            ],
            "asks": [{"seller_id": "seller-a", "reserve": 600}],
            "supply": 1,
        },
        "market-run",
    )
    assert mechanism == "second_price_auction"
    assert market["outcome"]["allocations"][0]["buyer_id"] == "buyer-a"
    assert market["outcome"]["payments"][0]["amount"]["amount"] == "900"
    assert market["properties"]["individual_rationality"]["holds"] is True
    assert market["gaps"][0]["status"] == "undersupplied"


def test_frontend_has_meaningful_offline_fallback_and_real_market_calls():
    source = (Path(__file__).parents[1] / "UI" / "workbench-api.js").read_text()
    assert "renderOfflinePage" in source
    assert "if(!WorkbenchAPI.online)" in source
    assert "'/operations/pricing'" in source
    assert "'/operations/market'" in source


def test_ui_runner_resolves_repo_and_src_from_ui_working_directory():
    repo = Path(__file__).parents[1]
    script = (
        "import run; run.prepare_import_paths(); "
        "import UI.server.app, datavalor; "
        "print(UI.server.app.__file__); print(datavalor.__file__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo / "UI",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str(repo / "UI" / "server" / "app.py") in result.stdout
    assert str(repo / "src" / "datavalor" / "__init__.py") in result.stdout


def test_server_module_bootstraps_src_before_datavalor_import():
    repo = Path(__file__).parents[1]
    package_source = (repo / "UI" / "__init__.py").read_text()
    server_source = (repo / "UI" / "server" / "app.py").read_text()
    assert "prepare_import_paths()" in package_source
    assert "from datavalor" in server_source
