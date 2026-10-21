from __future__ import annotations

from pathlib import Path


def test_scenario_catalog_is_diverse_and_execution_ready():
    from UI.services.scenarios import scenario_catalog

    scenarios = scenario_catalog()
    assert len(scenarios) >= 4
    assert len({scenario["domain"] for scenario in scenarios}) >= 4
    assert sum(len(scenario["products"]) for scenario in scenarios) >= 12
    assert all(len(scenario["products"]) >= 3 for scenario in scenarios)
    assert all(scenario["default_operations"] for scenario in scenarios)
    assert all("synthetic" in scenario["data_notice"].lower() for scenario in scenarios)
    for scenario in scenarios:
        for product in scenario["products"]:
            assert product["records"]
            assert product["rights"]["purposes"]
            assert {"quality", "freshness", "asking_price"} <= set(product["metadata"])


def test_loading_scenario_is_idempotent_and_persists_products(tmp_path):
    from UI.services.scenarios import load_scenario
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    first = load_scenario(workspace, "retail-demand")
    second = load_scenario(workspace, "retail-demand")

    assert first["loaded"] >= 3
    assert second["loaded"] == 0
    assert second["updated"] == first["loaded"]
    assert len(workspace.list("products")) == first["loaded"]


def test_batch_runs_real_operations_and_persists_comparison(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.scenarios import load_scenario
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    loaded = load_scenario(workspace, "retail-demand")
    product_ids = loaded["product_ids"][:2]
    batch = execute_batch(
        workspace,
        product_ids=product_ids,
        operations=["governance", "evaluation", "valuation", "pricing"],
        parameters={
            "governance": {"operation": "analytics"},
            "valuation": {"base_value": 80000, "evaluation_vector": {"quality": 0.9}},
            "pricing": {"model": "pricing.subscription", "period_fee": 12000},
        },
        label="Retail shortlist",
        scenario_id="retail-demand",
        seed=17,
    )

    assert batch["status"] == "succeeded"
    assert batch["summary"]["failed_stages"] == 0
    assert len(batch["items"]) == 2
    assert all(len(item["stages"]) == 4 for item in batch["items"])
    assert all(item["metrics"]["price"] == 16000.0 for item in batch["items"])
    assert all(item["metrics"]["value"] > 0 for item in batch["items"])
    assert workspace.get("batches", batch["batch_id"])["label"] == "Retail shortlist"
    assert len(workspace.list("runs")) == 8
    assert len(workspace.list("artifacts")) == 8


def test_batch_reports_partial_failures_without_losing_successful_items(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.scenarios import load_scenario
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    product_ids = load_scenario(workspace, "industrial-sensor")["product_ids"][:2]
    batch = execute_batch(
        workspace,
        product_ids=product_ids,
        operations=["profile", "not-an-operation", "pricing"],
        parameters={"pricing": {"model": "pricing.cost_plus", "base_cost": 100}},
        fail_fast=False,
    )

    assert batch["status"] == "partial"
    assert batch["summary"]["failed_stages"] == 2
    assert batch["summary"]["succeeded_stages"] == 4
    assert all(item["status"] == "partial" for item in batch["items"])
    assert all(item["stages"][1]["error"]["code"] == "execution_error" for item in batch["items"])


def test_every_builtin_scenario_completes_its_default_recipe(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.scenarios import load_scenario, scenario_catalog
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    for scenario in scenario_catalog():
        loaded = load_scenario(workspace, scenario["scenario_id"])
        batch = execute_batch(
            workspace,
            product_ids=loaded["product_ids"],
            operations=scenario["default_operations"],
            parameters=scenario["operation_parameters"],
            scenario_id=scenario["scenario_id"],
            seed=42,
        )
        assert batch["status"] == "succeeded", (scenario["scenario_id"], batch)
        if "market" in scenario["default_operations"]:
            assert batch["market_stage"]["status"] == "succeeded"


def test_scenario_recipe_uses_product_signals_for_discriminative_values(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.scenarios import load_scenario, scenario_by_id
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    scenario = scenario_by_id("retail-demand")
    product_ids = load_scenario(workspace, scenario["scenario_id"])["product_ids"]
    batch = execute_batch(
        workspace,
        product_ids=product_ids,
        operations=["valuation"],
        parameters=scenario["operation_parameters"],
    )

    values = {item["metrics"]["value"] for item in batch["items"]}
    assert len(values) >= 3


def test_workbench_routes_and_frontend_are_batch_first():
    from UI.server.app import create_app

    root = Path(__file__).parents[1]
    paths = {route.path for route in create_app().routes}
    assert {
        "/api/workbench/scenarios",
        "/api/workbench/scenarios/{scenario_id}/load",
        "/api/batches",
        "/api/batches/{batch_id}",
    } <= paths

    html = (root / "UI" / "index.html").read_text(encoding="utf-8")
    script = (root / "UI" / "app.js").read_text(encoding="utf-8")
    assert "Data → Value → Market" in html
    assert 'id="scenarioSelect"' in html
    assert 'id="assetTable"' in html
    assert 'id="runBatch"' in html
    assert 'id="resultCompare"' in html
    assert html.count('class="rail-nav') <= 3
    assert "/workbench/scenarios" in script
    assert "/batches" in script
    assert "selectedProductIds" in script
    assert "exportBatch" in script
