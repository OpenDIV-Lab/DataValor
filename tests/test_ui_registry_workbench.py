from __future__ import annotations


def _product(product_id: str, owner_id: str = "seller-a") -> dict:
    return {
        "product_id": product_id,
        "title": product_id,
        "owner_id": owner_id,
        "data": {"uri": f"memory://{product_id}", "format": "records", "record_count": 2},
        "rights": {"purposes": ["analytics"], "commercial_use": True},
        "metadata": {"asking_price": 100, "currency": "CNY"},
        "records": [{"value": 1}, {"value": 2}],
    }


def test_workspace_persists_registered_market_participants(tmp_path):
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    participant = {
        "participant_id": "buyer-a",
        "name": "采购方 A",
        "role": "buyer",
        "budget": 1000,
        "currency": "CNY",
    }
    workspace.put("participants", "buyer-a", participant)

    assert workspace.get("participants", "buyer-a") == participant
    assert workspace.list("participants") == [participant]


def test_loading_scenario_registers_buyers_and_sellers(tmp_path):
    from UI.services.scenarios import load_scenario
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    result = load_scenario(workspace, "ai-training")
    participants = workspace.list("participants")

    assert result["participants_registered"] >= 4
    assert {item["role"] for item in participants} == {"buyer", "seller"}
    assert {"foundation-model-team", "legal-publisher", "code-community"} <= {
        item["participant_id"] for item in participants
    }
    assert all(item["agent_config"]["enabled"] for item in participants)
    assert {item["agent_config"]["model"] for item in participants} >= {"budget_pacing", "reserve_optimizer"}


def test_batch_keeps_registered_input_artifact_lineage(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    workspace.put("products", "dataset-a", _product("dataset-a"))
    workspace.put("artifacts", "quality-report-a", {"artifact_id": "quality-report-a", "kind": "evaluation", "payload": {"score": 0.9}})

    batch = execute_batch(
        workspace,
        product_ids=["dataset-a"],
        operations=["valuation"],
        parameters={"valuation": {"base_value": 1000}},
        input_artifact_ids=["quality-report-a"],
    )

    assert batch["input_artifact_ids"] == ["quality-report-a"]
    assert batch["items"][0]["stages"][0]["input_artifact_ids"] == ["quality-report-a"]


def test_batch_automatically_includes_all_content_bound_to_selected_assets(tmp_path):
    from UI.services.batches import execute_batch
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    workspace.put("products", "dataset-a", _product("dataset-a"))
    workspace.put("products", "dataset-b", _product("dataset-b"))
    workspace.put("artifacts", "a-profile", {"artifact_id": "a-profile", "kind": "profile", "product_id": "dataset-a", "payload": {}})
    workspace.put("artifacts", "a-quality", {"artifact_id": "a-quality", "kind": "evaluation", "product_id": "dataset-a", "payload": {}})
    workspace.put("artifacts", "b-quality", {"artifact_id": "b-quality", "kind": "evaluation", "product_id": "dataset-b", "payload": {}})
    workspace.put("runs", "a-profile-run", {"run_id": "a-profile-run", "operation": "profile", "product_id": "dataset-a"})
    workspace.put("runs", "b-quality-run", {"run_id": "b-quality-run", "operation": "evaluation", "product_id": "dataset-b"})

    batch = execute_batch(
        workspace,
        product_ids=["dataset-a"],
        operations=["valuation"],
        parameters={"valuation": {"base_value": 1000}},
    )

    assert batch["input_artifact_ids"] == ["a-profile", "a-quality"]
    assert batch["input_run_ids"] == ["a-profile-run"]
    assert batch["items"][0]["stages"][0]["input_artifact_ids"] == ["a-profile", "a-quality"]
    assert batch["items"][0]["stages"][0]["input_run_ids"] == ["a-profile-run"]


def test_participant_registry_keeps_delegation_strategy(tmp_path):
    from UI.server.app import ParticipantPayload

    participant = ParticipantPayload(
        participant_id="buyer-agent",
        name="Buyer Agent",
        role="buyer",
        budget=5000,
        delegation_mode="platform_managed",
        strategy="budget_pacing",
        strategy_parameters={"shade": 0.9, "reserve_ratio": 0.1},
        agent_config={
            "enabled": True,
            "rationality": 0.95,
            "style": "balanced",
            "model": "budget_pacing",
            "preferred_mechanisms": ["bundle_matching"],
            "preferences": {"quality": 0.6, "freshness": 0.4},
        },
    )

    value = participant.model_dump()
    assert value["delegation_mode"] == "platform_managed"
    assert value["strategy"] == "budget_pacing"
    assert value["strategy_parameters"]["shade"] == 0.9
    assert value["agent_config"]["rationality"] == 0.95


def test_participant_agent_configuration_rejects_invalid_behavior():
    import pytest
    from pydantic import ValidationError
    from UI.server.app import ParticipantPayload

    with pytest.raises(ValidationError, match="rationality"):
        ParticipantPayload(participant_id="bad-agent", name="Bad", role="buyer", agent_config={"enabled": True, "rationality": 1.5})
    with pytest.raises(ValidationError, match="style"):
        ParticipantPayload(participant_id="bad-style", name="Bad", role="seller", agent_config={"enabled": True, "style": "random"})


def test_market_agents_generate_explainable_buyer_and_seller_orders():
    from UI.services.market_agents import generate_agent_orders

    products = [
        {
            **_product("dataset-a", "seller-a"),
            "metadata": {"asking_price": 100, "currency": "CNY", "quality": 0.9, "freshness": 0.8},
        },
        {
            **_product("dataset-b", "seller-b"),
            "metadata": {"asking_price": 80, "currency": "CNY", "quality": 0.7, "freshness": 0.95},
        },
    ]
    participants = [
        {
            "participant_id": "buyer-a", "role": "buyer", "budget": 300, "currency": "CNY",
            "agent_config": {"enabled": True, "rationality": 1, "style": "balanced", "model": "utility_maximizer", "preferences": {"quality": 0.7, "freshness": 0.3}},
        },
        {
            "participant_id": "seller-a", "role": "seller", "product_ids": ["dataset-a"], "currency": "CNY",
            "agent_config": {"enabled": True, "rationality": 1, "style": "conservative", "model": "reserve_optimizer", "preferences": {}},
            "strategy_parameters": {"markup": 0.1},
        },
    ]
    artifacts = [
        {"artifact_id": "value-a", "product_id": "dataset-a", "kind": "valuation", "created_at": "2026-01-01T00:00:00Z", "payload": {"estimates": [{"value": 150, "currency": "CNY"}]}},
        {"artifact_id": "price-a", "product_id": "dataset-a", "kind": "pricing", "created_at": "2026-01-02T00:00:00Z", "payload": {"price": {"amount": 120, "currency": "CNY"}}},
    ]

    result = generate_agent_orders(
        participants, products, artifacts,
        participant_ids=["buyer-a", "seller-a"], product_ids=["dataset-a", "dataset-b"],
        mechanism="multi_attribute_matching",
    )

    assert {order["side"] for order in result["orders"]} == {"bid", "ask"}
    assert all(order["agent_generated"] is True for order in result["orders"])
    assert all(order["explanation"]["model"] for order in result["orders"])
    assert result["diagnostics"]["generated"] == len(result["orders"])
    assert result["signals"]["dataset-a"]["latest_value"] == 150
    assert result["signals"]["dataset-a"]["latest_price"] == 120


def test_market_agents_skip_manual_participants():
    from UI.services.market_agents import generate_agent_orders

    result = generate_agent_orders(
        [{"participant_id": "buyer-manual", "role": "buyer", "budget": 100, "agent_config": {"enabled": False}}],
        [_product("dataset-a")], [],
        participant_ids=["buyer-manual"], product_ids=["dataset-a"], mechanism="first_price_auction",
    )

    assert result["orders"] == []
    assert result["diagnostics"]["skipped"][0]["reason"] == "agent_disabled"


def test_market_agents_do_not_mix_incomparable_price_scales():
    from UI.services.market_agents import generate_agent_orders

    product = {**_product("dataset-a", "seller-a"), "metadata": {"asking_price": 100, "currency": "CNY", "quality": 0.9, "freshness": 0.8}}
    result = generate_agent_orders(
        [{
            "participant_id": "seller-a", "role": "seller", "product_ids": ["dataset-a"], "currency": "CNY",
            "agent_config": {"enabled": True, "rationality": 1, "style": "balanced", "model": "reserve_optimizer"},
            "strategy_parameters": {"markup": 0.1},
        }],
        [product],
        [{"artifact_id": "usage-quote", "product_id": "dataset-a", "kind": "pricing", "created_at": "2026-01-01T00:00:00Z", "payload": {"price": {"amount": 5, "currency": "CNY"}}}],
        participant_ids=["seller-a"], product_ids=["dataset-a"], mechanism="bundle_matching",
    )

    assert result["signals"]["dataset-a"]["latest_price"] == 5
    assert result["signals"]["dataset-a"]["decision_price"] == 100
    assert result["orders"][0]["amount"] == 110
    assert result["orders"][0]["explanation"]["price_basis"] == "asking_price_scale_guard"


def test_agent_order_route_is_registered(tmp_path):
    from UI.server.app import create_app

    paths = {route.path for route in create_app(tmp_path).routes}
    assert "/api/market/agent-orders" in paths


def test_participant_dialog_cancel_controls_do_not_submit_registration():
    from pathlib import Path

    root = Path(__file__).parents[1]
    html = (root / "UI" / "index.html").read_text()
    script = (root / "UI" / "app.js").read_text()

    assert 'id="closeParticipantDialog" type="button"' in html
    assert 'id="cancelParticipant" type="button"' in html
    assert "function closeParticipantDialog()" in script
    assert '$("#cancelParticipant").addEventListener("click", closeParticipantDialog)' in script
    assert '$("#closeParticipantDialog").addEventListener("click", closeParticipantDialog)' in script


def test_registry_routes_and_dashboard_module_statistics(tmp_path):
    from UI.server.app import ParticipantPayload, ProductPayload, create_app

    app = create_app(tmp_path)
    endpoints = {
        (route.path, next(iter(route.methods))): route.endpoint
        for route in app.routes
        if hasattr(route, "endpoint") and getattr(route, "methods", None)
    }
    endpoints[("/api/participants", "POST")](
        ParticipantPayload(participant_id="buyer-a", name="Buyer A", role="buyer", budget=900, currency="CNY")
    )
    endpoints[("/api/products", "POST")](ProductPayload(**_product("dataset-a")))

    participant_data = endpoints[("/api/participants", "GET")]()
    dashboard = endpoints[("/api/dashboard", "GET")]()
    participant_data = participant_data["data"]
    dashboard = dashboard["data"]

    assert participant_data["participants"][0]["participant_id"] == "buyer-a"
    assert dashboard["summary"]["participants"] == 1
    assert dashboard["summary"]["total_records"] == 2
    assert dashboard["modules"]["products"]["registered"] == 1
    assert set(dashboard["modules"]) >= {"governance", "profile", "evaluation", "valuation", "pricing", "market"}


def test_dashboard_counts_bundle_and_multi_attribute_market_matches(tmp_path):
    from UI.server.app import create_app
    from UI.services.workspace import Workspace

    workspace = Workspace(tmp_path)
    workspace.put(
        "artifacts",
        "bundle-result",
        {
            "artifact_id": "bundle-result",
            "kind": "market",
            "payload": {"outcome": {"allocations": []}, "bundle_selection": {"matches": [{"buyer_id": "buyer-a"}]}},
        },
    )
    workspace.put(
        "artifacts",
        "attribute-result",
        {
            "artifact_id": "attribute-result",
            "kind": "market",
            "payload": {"outcome": {"allocations": []}, "multi_attribute_matches": [{"buyer_id": "buyer-b"}]},
        },
    )
    app = create_app(tmp_path)
    dashboard_endpoint = next(route.endpoint for route in app.routes if route.path == "/api/dashboard")

    dashboard = dashboard_endpoint()["data"]

    assert dashboard["modules"]["market"]["allocations"] == 2
