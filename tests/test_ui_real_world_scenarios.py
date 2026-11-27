from __future__ import annotations

from UI.services.real_world_scenarios import real_world_scenarios
from UI.services.scenarios import _scenario_participants, scenario_catalog
from UI.services.workspace import Workspace
from UI.services.scenarios import load_scenario


def test_real_world_catalog_has_source_grounded_applications() -> None:
    scenarios = real_world_scenarios()

    assert [item["scenario_id"] for item in scenarios] == [
        "real-nyc-mobility",
        "real-pjm-energy",
        "real-mimic-rwe",
        "real-sec-fred-investment",
    ]
    for scenario in scenarios:
        assert scenario["evidence_level"] == "source_grounded_sample"
        assert scenario["default_operations"] == ["governance", "profile", "evaluation", "valuation", "pricing", "market"]
        assert len(scenario["products"]) >= 3
        assert len(scenario["participants"]) >= 3
        assert {item["role"] for item in scenario["participants"]} >= {"buyer", "seller"}
        assert len(scenario["business_context"]["process_steps"]) >= 5
        assert len(scenario["business_context"]["metric_dimensions"]) >= 4
        assert scenario["business_context"]["demand"]
        assert scenario["assumptions"]["prices_are_observed"] is False
        assert scenario["assumptions"]["note"]
        assert all(source["url"].startswith("https://") for source in scenario["sources"])
        assert all(source["publisher"] and source["license"] for source in scenario["sources"])


def test_real_products_keep_record_level_provenance_and_observed_values() -> None:
    scenarios = {item["scenario_id"]: item for item in real_world_scenarios()}

    mobility = scenarios["real-nyc-mobility"]
    assert mobility["products"][0]["records"][0]["tpep_pickup_datetime"] == "2024-01-01T00:57:55.000"
    assert mobility["products"][0]["records"][0]["pulocationid"] == 186
    assert mobility["products"][0]["metadata"]["provenance"]["dataset_id"] == "rwwi-khbc"

    energy = scenarios["real-pjm-energy"]
    assert energy["products"][0]["records"][0]["value"] == 114253
    assert energy["products"][0]["records"][0]["value_units"] == "megawatthours"
    assert energy["products"][0]["metadata"]["provenance"]["publisher"] == "U.S. Energy Information Administration"

    clinical = scenarios["real-mimic-rwe"]
    assert clinical["products"][0]["records"][0]["hadm_id"] == 24181354
    assert clinical["products"][1]["records"][0]["icd_code"] == "4139"
    assert clinical["products"][2]["records"][0]["labevent_id"] == 172061
    assert clinical["products"][0]["rights"]["license"] == "ODbL-1.0"

    finance = scenarios["real-sec-fred-investment"]
    first_fact = finance["products"][0]["records"][0]
    assert first_fact["issuer"] == "Apple Inc."
    assert first_fact["assets_usd"] == 353_514_000_000
    assert first_fact["revenue_usd"] == 119_575_000_000
    assert first_fact["accession"] == "0000320193-24-000006"
    assert finance["products"][1]["records"][0] == {
        "source_record_id": "DFF:2024-07-01",
        "observation_date": "2024-07-01",
        "series_id": "DFF",
        "value": 5.33,
        "unit": "Percent",
    }
    first_signal = finance["products"][2]["records"][0]
    assert first_signal["as_of_date"] == "2024-07-01"
    assert first_signal["issuer"] == "Apple Inc."
    assert first_signal["source_accession"] == "0000320193-24-000069"
    assert first_signal["filing_lag_days"] == 59

    for scenario in scenarios.values():
        for product in scenario["products"]:
            provenance = product["metadata"]["provenance"]
            assert provenance["source_url"].startswith("https://")
            assert provenance["sample_kind"] in {"official_records", "derived_from_official_records"}
            assert len(product["records"]) >= 6


def test_real_scenarios_are_executable_and_load_idempotently(tmp_path) -> None:
    catalog = {item["scenario_id"]: item for item in scenario_catalog()}
    assert set(real_world_scenarios()[index]["scenario_id"] for index in range(3)) <= set(catalog)

    workspace = Workspace(tmp_path)
    first = load_scenario(workspace, "real-pjm-energy")
    second = load_scenario(workspace, "real-pjm-energy")

    assert first["loaded"] == 3
    assert second["loaded"] == 0
    assert second["updated"] == 3
    assert first["participants_registered"] == len(catalog["real-pjm-energy"]["participants"])
    participants = _scenario_participants(catalog["real-pjm-energy"])
    assert {item["participant_id"] for item in participants} == {
        item["participant_id"] for item in catalog["real-pjm-energy"]["participants"]
    }


def test_case_defaults_name_real_decision_metrics_and_market_orders() -> None:
    for scenario in real_world_scenarios():
        parameters = scenario["operation_parameters"]
        assert parameters["evaluation"]["metrics"]
        assert parameters["valuation"]["method"].startswith("valuation.")
        assert parameters["pricing"]["model"].startswith("pricing.")
        assert parameters["market"]["mechanism"]
        assert parameters["market"].get("bids") or parameters["market"].get("buyer_id")
        assert parameters["market"].get("asks")
        assert scenario["business_context"]["decision_metric"]


def test_financial_application_models_point_in_time_research_procurement() -> None:
    finance = {item["scenario_id"]: item for item in real_world_scenarios()}["real-sec-fred-investment"]

    metric_names = {item["name"] for item in finance["business_context"]["metric_dimensions"]}
    assert {"point-in-time integrity", "filing latency", "issuer-period coverage", "shadow ranking gain"} <= metric_names
    assert {item["role"] for item in finance["participants"]} == {"buyer", "seller"}
    assert finance["operation_parameters"]["valuation"]["method"] == "valuation.counterfactual"
    assert finance["operation_parameters"]["pricing"]["model"] == "pricing.subscription"
    assert finance["operation_parameters"]["market"]["mechanism"] == "bundle_matching"
    assert sum(item["reserve"] for item in finance["operation_parameters"]["market"]["asks"]) < finance["operation_parameters"]["market"]["budget"]
