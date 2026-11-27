from __future__ import annotations

import json
import subprocess
from pathlib import Path

from UI.services.real_world_scenarios import real_world_scenarios


ROOT = Path(__file__).resolve().parents[1]


def run_engine(expression: str, payload: dict) -> dict:
    program = f"""
const engine = require('./UI/offline-engine.js');
const input = JSON.parse(process.argv[1]);
const output = {expression};
process.stdout.write(JSON.stringify(output));
"""
    result = subprocess.run(
        ["node", "-e", program, json.dumps(payload)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def run_offline_api(program_body: str, payload: dict) -> dict:
    program = f"""
const fs = require('fs');
const vm = require('vm');
global.window = {{ DATAVALOR_STANDALONE: {{ scenarios: [], schemas: {{}}, components: [] }} }};
const storage = new Map();
window.localStorage = {{ getItem: (key) => storage.has(key) ? storage.get(key) : null, setItem: (key, value) => storage.set(key, value) }};
global.OfflineExecutionEngine = require('./UI/offline-engine.js');
vm.runInThisContext(fs.readFileSync('./UI/offline-workbench.js', 'utf8') + '\\n;globalThis.__offlineApi = OfflineWorkbench;');
const input = JSON.parse(process.argv[1]);
(async () => {{
  {program_body}
}})().catch((error) => {{ console.error(error.stack); process.exit(1); }});
"""
    result = subprocess.run(
        ["node", "-e", program, json.dumps(payload)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def sample_product() -> dict:
    return {
        "product_id": "sample",
        "title": "Sample",
        "owner_id": "seller",
        "records": [
            {"x": 1, "label": "a"},
            {"x": 2, "label": ""},
            {"x": 2, "label": ""},
        ],
        "data": {"record_count": 3},
        "rights": {"purposes": ["analytics"], "commercial_use": True},
        "metadata": {"quality": 0.8, "freshness": 0.9, "asking_price": 80, "currency": "USD"},
    }


def test_profile_and_evaluation_compute_from_records() -> None:
    payload = {"product": sample_product()}

    result = run_engine(
        "({profile: engine.execute('profile', [input.product], {}), evaluation: engine.execute('evaluation', [input.product], {modality: 'tabular', metrics: ['basic.completeness', 'basic.duplicate_rate'], required_fields: ['x', 'label']})})",
        payload,
    )

    assert result["profile"]["producer"] == "offline.basic_data_profiler"
    assert result["profile"]["result"]["record_count"] == 3
    assert {item["name"] for item in result["profile"]["result"]["fields"]} == {"x", "label"}
    metrics = {item["name"]: item for item in result["evaluation"]["result"]["metrics"]}
    assert metrics["basic.completeness"]["value"] == 2 / 3
    assert metrics["basic.duplicate_rate"]["value"] == 1 / 3
    assert all(0 <= item["value"] <= 1 for item in metrics.values())


def test_valuation_and_pricing_use_transparent_formulas() -> None:
    payload = {"product": sample_product()}

    result = run_engine(
        "({valuation: engine.execute('valuation', [input.product], {method: 'valuation.time_decay', base_value: 100000, age_days: 30, half_life_days: 30, time_sensitivity: 1, currency: 'USD'}), pricing: engine.execute('pricing', [input.product], {model: 'pricing.subscription', period_fee: 50000, included_usage: 1000, usage: 1250, overage_unit_price: 18, currency: 'USD'})})",
        payload,
    )

    estimate = result["valuation"]["result"]["estimates"][0]
    assert result["valuation"]["producer"] == "offline.valuation.time_decay"
    assert estimate["value"] == 50000
    assert estimate["components"]["decay_factor"] == 0.5
    quote = result["pricing"]["result"]
    assert result["pricing"]["producer"] == "offline.pricing.subscription"
    assert quote["price"] == {"amount": 54500, "currency": "USD"}
    assert quote["components"]["overage_charge"] == 4500


def test_second_price_market_allocates_and_charges_runner_up() -> None:
    product = sample_product()
    parameters = {
        "mechanism": "second_price_auction",
        "currency": "USD",
        "bids": [
            {"bid_id": "b1", "buyer_id": "buyer-a", "product_ids": ["sample"], "amount": 120, "quantity": 1, "currency": "USD"},
            {"bid_id": "b2", "buyer_id": "buyer-b", "product_ids": ["sample"], "amount": 100, "quantity": 1, "currency": "USD"},
        ],
        "asks": [{"ask_id": "a1", "seller_id": "seller", "product_ids": ["sample"], "reserve": 80, "quantity": 1, "currency": "USD"}],
    }

    result = run_engine("engine.execute('market', [input.product], input.parameters)", {"product": product, "parameters": parameters})

    outcome = result["result"]["outcome"]
    assert result["producer"] == "offline.second_price_auction"
    assert outcome["allocations"][0]["buyer_id"] == "buyer-a"
    assert outcome["payments"][0]["amount"] == {"amount": 100, "currency": "USD"}
    assert result["result"]["properties"]["individually_rational"] is True


def test_batch_persists_runs_artifacts_and_metrics() -> None:
    workspace = {"products": [sample_product()], "participants": [], "artifacts": [], "runs": [], "batches": []}
    request = {
        "product_ids": ["sample"],
        "operations": ["governance", "evaluation", "valuation", "pricing"],
        "parameters": {
            "governance": {"operation": "analytics"},
            "evaluation": {"modality": "tabular", "metrics": ["basic.completeness"]},
            "valuation": {"method": "valuation.weighted_user_task", "base_value": 1000, "evaluation_vector": {"quality": 0.8}},
            "pricing": {"model": "pricing.value_based", "estimated_value": 800, "buyer_share": 0.5, "floor": 0, "ceiling": 1000},
        },
        "label": "offline batch",
        "scenario_id": "case",
        "seed": 7,
        "fail_fast": False,
    }

    result = run_engine("(() => { const batch = engine.executeBatch(input.workspace, input.request); return {batch, workspace: input.workspace}; })()", {"workspace": workspace, "request": request})

    assert result["batch"]["status"] == "succeeded"
    assert result["batch"]["summary"]["succeeded_stages"] == 4
    assert result["batch"]["items"][0]["metrics"]["value"] == 800
    assert result["batch"]["items"][0]["metrics"]["price"] == 400
    assert len(result["workspace"]["artifacts"]) == 4
    assert len(result["workspace"]["runs"]) == 4
    assert len(result["workspace"]["batches"]) == 1
    assert all(item["producer"].startswith("offline.") for item in result["workspace"]["artifacts"])


def test_agent_orders_respect_roles_budget_and_reserve() -> None:
    product = sample_product()
    workspace = {
        "products": [product],
        "participants": [
            {"participant_id": "buyer", "role": "buyer", "budget": 100, "currency": "USD", "agent_config": {"enabled": True, "rationality": 1, "style": "balanced", "model": "budget_pacing", "preferences": {"quality": 0.5, "freshness": 0.2, "price": 0.3}}},
            {"participant_id": "seller", "role": "seller", "budget": 70, "currency": "USD", "product_ids": ["sample"], "agent_config": {"enabled": True, "rationality": 1, "style": "balanced", "model": "reserve_optimizer", "preferences": {}}},
        ],
        "artifacts": [], "runs": [], "batches": [],
    }

    result = run_engine("engine.generateAgentOrders(input.workspace, input.request)", {"workspace": workspace, "request": {"participant_ids": ["buyer", "seller"], "product_ids": ["sample"], "mechanism": "mcafee_double_auction"}})

    assert [item["side"] for item in result["orders"]] == ["bid", "ask"]
    assert result["orders"][0]["amount"] <= 100
    assert result["orders"][1]["amount"] >= 70
    assert result["diagnostics"]["generated"] == 2


def test_offline_api_executes_and_persists_batch() -> None:
    request = {
        "product_ids": ["sample"],
        "operations": ["profile", "valuation"],
        "parameters": {
            "profile": {},
            "valuation": {"method": "valuation.weighted_user_task", "base_value": 1000, "evaluation_vector": {"utility": 0.75}},
        },
        "label": "browser batch",
    }
    result = run_offline_api(
        """
await __offlineApi.request('/products', {method: 'POST', body: JSON.stringify(input.product)});
const response = await __offlineApi.request('/batches', {method: 'POST', body: JSON.stringify(input.request)});
const batches = await __offlineApi.request('/batches');
const runs = await __offlineApi.request('/runs');
const artifacts = await __offlineApi.request('/artifacts');
process.stdout.write(JSON.stringify({response, batches, runs, artifacts}));
""",
        {"product": sample_product(), "request": request},
    )

    assert result["response"]["batch"]["status"] == "succeeded"
    assert len(result["batches"]["batches"]) == 1
    assert len(result["runs"]["runs"]) == 2
    assert len(result["artifacts"]["artifacts"]) == 2
    assert result["artifacts"]["artifacts"][1]["payload"]["estimates"][0]["value"] == 750


def test_offline_engine_completes_each_source_grounded_application() -> None:
    scenarios = real_world_scenarios()
    payload = {
        "cases": [
            {
                "scenario_id": scenario["scenario_id"],
                "products": scenario["products"],
                "request": {
                    "product_ids": [product["product_id"] for product in scenario["products"]],
                    "operations": scenario["default_operations"],
                    "parameters": scenario["operation_parameters"],
                    "scenario_id": scenario["scenario_id"],
                    "seed": 42,
                },
            }
            for scenario in scenarios
        ]
    }

    result = run_engine(
        "input.cases.map((item) => { const workspace = {products: item.products, participants: [], artifacts: [], runs: [], batches: []}; const batch = engine.executeBatch(workspace, item.request); return {scenario_id: item.scenario_id, status: batch.status, succeeded_stages: batch.summary.succeeded_stages, failed_stages: batch.summary.failed_stages, persisted: workspace.batches.length}; })",
        payload,
    )

    assert [item["scenario_id"] for item in result] == [scenario["scenario_id"] for scenario in scenarios]
    assert all(item["status"] == "succeeded" for item in result)
    assert all(item["failed_stages"] == 0 for item in result)
    assert all(item["succeeded_stages"] == 16 for item in result)
    assert all(item["persisted"] == 1 for item in result)
