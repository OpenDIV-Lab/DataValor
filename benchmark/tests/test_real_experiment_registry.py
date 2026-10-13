from __future__ import annotations

import json
from pathlib import Path

import yaml
from datamechbench.real_experiment import (
    authorize_confirmatory,
    authorize_kdd_heldout_protocol,
    authorize_pg_elr_confirmatory,
    freeze_kdd_heldout_protocol,
    freeze_pg_elr_protocol,
    freeze_real_protocol,
)
from datamechbench.runner import build_registry
from datamechbench.settings.valuation_real import (
    REAL_GPU_IDS,
    REAL_SPLIT_SEEDS,
    real_valuation_settings,
)


def test_real_registry_freezes_ten_settings_protocol_and_disjoint_splits() -> None:
    settings = real_valuation_settings()
    assert len(settings) == 10
    assert len({setting.setting_id for setting in settings}) == 10
    assert {setting.dataset_id for setting in settings} == {
        "breast_cancer", "wine", "adult", "california_housing", "diabetes",
        "digits", "ag_news", "20newsgroups", "fashion_mnist", "cifar10_subset",
    }
    assert REAL_SPLIT_SEEDS == (11, 29, 47)
    assert REAL_GPU_IDS == (1, 2, 3, 4, 5, 6, 7)
    assert all(0 not in setting.gpu_ids for setting in settings)
    development = {s.dataset_id for s in settings if s.evidence_split == "development"}
    confirmatory = {s.dataset_id for s in settings if s.evidence_split == "confirmatory"}
    assert len(development) == 8 and len(confirmatory) == 2
    assert not development & confirmatory
    for setting in settings:
        assert setting.split_seeds == REAL_SPLIT_SEEDS
        assert setting.budgets == ((192, 224) if setting.n_owners == 8 else (448, 640))
        capacities = tuple(f.capacity for f in setting.fidelities)
        assert capacities in {(16, 48, 128), (20, 60, 120), (1, 3, 6)}


def test_real_yaml_configs_match_registry_and_cpu_thread_limits() -> None:
    root = Path(__file__).parents[1] / "configs"
    development = yaml.safe_load((root / "elr_vrds_real_development.yaml").read_text())
    confirmatory = yaml.safe_load((root / "elr_vrds_real_confirmatory.yaml").read_text())
    smoke = yaml.safe_load((root / "elr_vrds_real_smoke.yaml").read_text())
    assert development["physical_gpus"] == [1, 2, 3, 4, 5, 6, 7]
    assert confirmatory["physical_gpus"] == [1, 2, 3, 4, 5, 6, 7]
    assert development["cpu_threads_per_job"] > 0
    assert development["settings"] == [
        s.setting_id for s in real_valuation_settings() if s.evidence_split == "development"
    ]
    assert confirmatory["settings"] == [
        s.setting_id for s in real_valuation_settings() if s.evidence_split == "confirmatory"
    ]
    assert smoke["physical_gpus"] == [1]
    assert smoke["n_owners"] == 3


def test_confirmatory_gate_requires_untampered_development_freeze(tmp_path: Path) -> None:
    marker = tmp_path / "real_protocol_freeze.json"
    frozen_inputs = {"code": "abc", "development_config": "def", "sources": "ghi"}
    try:
        authorize_confirmatory(marker, expected_input_hashes=frozen_inputs)
    except RuntimeError as error:
        assert "freeze marker" in str(error)
    else:
        raise AssertionError("confirmatory access opened without a freeze")
    freeze = freeze_real_protocol(
        marker,
        input_hashes=frozen_inputs,
        selected_fidelity_rule="min_validation_residual_variance_times_cost",
        budgets={"n8": [192, 224], "n10": [448, 640]},
        methods=["mc_shapley", "elr_vrds"],
        metrics=["rmse", "spearman", "wall_seconds"],
        development_artifact_hashes={"real-breast-rf-n8": "artifact-a"},
        fidelity_record={"selection_source": "validation_only"},
    )
    authorized = authorize_confirmatory(marker, expected_input_hashes=frozen_inputs)
    assert authorized.protocol_hash == freeze.protocol_hash

    payload = yaml.safe_load(marker.read_text())
    payload["input_hashes"]["code"] = "tampered"
    marker.write_text(json.dumps(payload))
    try:
        authorize_confirmatory(marker, expected_input_hashes=frozen_inputs)
    except RuntimeError as error:
        assert "hash" in str(error)
    else:
        raise AssertionError("tampered freeze marker was accepted")


def test_freeze_rejects_test_derived_fidelity_fields(tmp_path: Path) -> None:
    try:
        freeze_real_protocol(
            tmp_path / "bad.json",
            input_hashes={"code": "a"},
            selected_fidelity_rule="fixed",
            budgets={"n8": [192]},
            methods=["elr_vrds"],
            metrics=["rmse"],
            development_artifact_hashes={"dev": "x"},
            fidelity_record={"test_utility": 0.9},
        )
    except ValueError as error:
        assert "test-derived" in str(error)
    else:
        raise AssertionError("test-derived fidelity selection was accepted")


def _pg_elr_hashes() -> dict[str, str]:
    return {
        "selection_record": "selection-a",
        "method_source": "method-a",
        "development_config": "development-a",
        "confirmatory_config": "confirmatory-a",
        "statistics_source": "statistics-a",
        "report_template": "template-a",
    }


def test_pg_elr_gate_binds_every_frozen_input_hash(tmp_path: Path) -> None:
    marker = tmp_path / "pg-elr-freeze.json"
    hashes = _pg_elr_hashes()
    try:
        authorize_pg_elr_confirmatory(marker, expected_source_hashes=hashes)
    except RuntimeError as error:
        assert "freeze marker" in str(error)
    else:
        raise AssertionError("PG-ELR confirmation opened without a freeze")

    frozen = freeze_pg_elr_protocol(
        marker,
        selection={"probe_players": 5, "calibration_seeds": 20},
        methods=["bd_pg_elr", "shapiq_svarm"],
        budgets={"n8": [192, 224], "n10": [448, 640]},
        metrics=["mae", "normalized_mae", "utility_regret"],
        source_hashes=hashes,
        feature_model_hashes={"resnet18": "weights-a", "neural_head": "model-a"},
    )
    authorized = authorize_pg_elr_confirmatory(
        marker, expected_source_hashes=hashes
    )
    assert authorized.protocol_hash == frozen.protocol_hash
    assert authorized.payload["confirmatory_utilities"] is None

    for key in hashes:
        changed = {**hashes, key: "changed"}
        try:
            authorize_pg_elr_confirmatory(marker, expected_source_hashes=changed)
        except RuntimeError as error:
            assert "hashes" in str(error)
        else:
            raise AssertionError(f"changed {key} was accepted")


def test_pg_elr_freeze_rejects_embedded_confirmatory_outcomes(tmp_path: Path) -> None:
    for bad_selection in (
        {"probe_players": 5, "confirmatory_result": "win"},
        {"probe_players": 5, "test_utility": 0.9},
    ):
        try:
            freeze_pg_elr_protocol(
                tmp_path / "bad-pg-elr.json",
                selection=bad_selection,
                methods=["bd_pg_elr"],
                budgets={"n8": [192, 224]},
                metrics=["mae"],
                source_hashes=_pg_elr_hashes(),
                feature_model_hashes={"resnet18": "a"},
            )
        except ValueError as error:
            assert "outcome-derived" in str(error)
        else:
            raise AssertionError("outcome-derived PG-ELR selection was frozen")


def test_kdd_heldout_freeze_binds_sources_transformations_and_contrasts(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "kdd-heldout.json"
    sources = {
        "valuation": [{"source_id": "openml-44", "expected_md5": "abc"}],
        "procurement": [{"source_id": "chile-2024-03-15"}],
        "trading": [{"source_id": "elexon-2024-03-15-sp8"}],
    }
    freeze = freeze_kdd_heldout_protocol(
        marker,
        sources=sources,
        transformations={"winsor_quantiles": [0.025, 0.975]},
        contrasts=[{
            "contrast_id": "v-primary",
            "inference_unit": "independent_block",
            "metric": "replication_rank_gain",
        }],
        headline_methods={"valuation": ["shapley_exact", "banzhaf_exact"]},
        development_artifact_hashes={"raw_results": "a" * 64},
        protocol_revision="2",
        amendment={
            "supersedes": "protocol-v1-hash",
            "reason": "source endpoint amendment before mechanism outcomes",
            "excluded_access_pilots": ["2024-03-15"],
        },
    )

    authorized = authorize_kdd_heldout_protocol(marker, expected_sources=sources)
    assert authorized.protocol_hash == freeze.protocol_hash
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["manifest_kind"] == "confirmatory_protocol"
    assert payload["protocol_revision"] == "2"
    assert payload["amendment"]["supersedes"] == "protocol-v1-hash"
    assert payload["amendment"]["excluded_access_pilots"] == ["2024-03-15"]
    assert payload["confirmatory_outcomes"] is None
    assert payload["contrasts"][0]["inference_unit"] == "independent_block"


def test_kdd_heldout_freeze_rejects_outcome_derived_selection(tmp_path: Path) -> None:
    try:
        freeze_kdd_heldout_protocol(
            tmp_path / "bad-heldout.json",
            sources={"valuation": [{"source_id": "openml-44"}]},
            transformations={"selected_after_test_metric": 0.9},
            contrasts=[],
            headline_methods={"valuation": ["shapley_exact"]},
            development_artifact_hashes={"raw_results": "a" * 64},
        )
    except ValueError as error:
        assert "outcome-derived" in str(error)
    else:
        raise AssertionError("outcome-derived held-out selection was accepted")


def test_frozen_kdd_heldout_protocol_matches_config_and_has_no_outcomes() -> None:
    benchmark = Path(__file__).parents[1]
    config = yaml.safe_load(
        (benchmark / "configs" / "kdd_heldout_confirmatory.yaml").read_text(
            encoding="utf-8"
        )
    )
    marker = benchmark / "evidence" / "kdd_heldout_protocol_v6.json"

    authorized = authorize_kdd_heldout_protocol(
        marker, expected_sources=config["sources"]
    )

    assert authorized.payload["confirmatory_outcomes"] is None
    assert len(authorized.payload["sources"]["valuation"]) == 3
    assert len(authorized.payload["sources"]["procurement"]) == 3
    assert authorized.payload["protocol_revision"] == "6"
    assert authorized.payload["amendment"]["excluded_access_pilots"] == [
        "2024-03-15", "2024-04-12"
    ]
    assert authorized.payload["sources"]["trading"][:3] == [
        {"date": "2024-03-15", "settlement_periods": [8, 24, 40]},
        {"date": "2024-06-14", "settlement_periods": [8, 24, 40]},
        {"date": "2024-09-13", "settlement_periods": [8, 24, 40]},
    ]
    assert len(authorized.payload["contrasts"]) == 6
    assert {
        contrast["inference_unit"] for contrast in authorized.payload["contrasts"]
    } == {"independent_block"}


def test_kdd_contrasts_use_registered_metrics_and_headline_methods() -> None:
    benchmark = Path(__file__).parents[1]
    config = yaml.safe_load(
        (benchmark / "configs" / "kdd_heldout_confirmatory.yaml").read_text(
            encoding="utf-8"
        )
    )
    metric_catalog = yaml.safe_load(
        (benchmark / "catalog" / "metrics.yaml").read_text(encoding="utf-8")
    )
    metrics_by_track = {
        track: {
            metric["metric_id"]
            for metric in metric_catalog["metrics"]
            if metric["track"] in {track, "all"}
        }
        for track in ("valuation", "procurement", "trading")
    }
    registry = build_registry()
    specs = {spec.method_id: spec for spec in registry.specs()}
    case_types = {
        "valuation": "real_owner_data",
        "procurement": "real_owner_data",
        "trading": "double_auction",
    }
    for contrast in config["contrasts"]:
        assert contrast["metric"] in metrics_by_track[contrast["track"]]
        assert contrast["method_a"] in config["headline_methods"][contrast["track"]]
        assert contrast["method_b"] in config["headline_methods"][contrast["track"]]
    for track, methods in config["headline_methods"].items():
        for method in methods:
            assert specs[method].track == track
            assert case_types[track] in specs[method].supported_case_types


def test_kdd_heldout_config_freezes_the_released_result_surface() -> None:
    benchmark = Path(__file__).parents[1]
    config = yaml.safe_load(
        (benchmark / "configs" / "kdd_heldout_confirmatory.yaml").read_text(
            encoding="utf-8"
        )
    )
    observed: dict[str, set[str]] = {
        "valuation": set(),
        "procurement": set(),
        "trading": set(),
    }
    for line in (
        benchmark / "outputs" / "kdd_heldout_confirmatory" / "raw_results.jsonl"
    ).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        observed[row["track"]].update(row["metrics"])

    contract = config["result_contract"]
    assert contract["diagnostic_keys"] == []
    assert {
        track: set(metric_ids)
        for track, metric_ids in contract["metric_ids"].items()
    } == observed
    assert "normalized_oracle_gain_ratio" not in contract["metric_ids"]["procurement"]
    assert "value_oracle_queries" not in contract["metric_ids"]["procurement"]
