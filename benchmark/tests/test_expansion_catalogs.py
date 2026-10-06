from __future__ import annotations

from datamechbench.expectations import load_expectations, load_metric_definitions
from datamechbench.leaderboard import SETTING_PRIMARY_METRICS
from datamechbench.provenance import load_provenance, validate_provenance
from datamechbench.qualification import load_qualification_policies
from datamechbench.runner import BenchmarkConfig, build_registry, load_config, run_benchmark

NEW_METHODS = {
    "volume_shapley",
    "robust_volume_shapley",
    "jt_greedy_tm",
    "jt_random_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
}

PAPER_EXACT_EXPANSION_METHODS = {
    "jt_greedy_tm",
    "jt_random_tm",
    "jt_random_eom",
    "jt_deterministic_eom",
}

PAPER_VARIANT_EXPANSION_METHODS = {
    "volume_shapley",
    "robust_volume_shapley",
}

NEW_METRICS = {
    "replication_reward_share_gain",
    "replication_score_inflation_ratio",
    "characteristic_replication_inflation_ratio",
    "replication_owner_rank_change",
    "procurement_efficiency_loss",
    "largest_singleton_share",
    "normalized_trade_loss",
    "participant_surplus_ratio",
    "efficient_trade_count",
}


def test_expansion_methods_have_complete_paper_provenance() -> None:
    catalog = load_provenance()
    validate_provenance(build_registry(), catalog)

    assert NEW_METHODS <= set(catalog.mechanisms)
    for method_id in NEW_METHODS:
        record = catalog.mechanisms[method_id]
        assert record.primary_reference.kind == "paper"
    for method_id in PAPER_EXACT_EXPANSION_METHODS:
        record = catalog.mechanisms[method_id]
        assert record.provenance_kind == "paper_exact"
        assert not record.deviations
    for method_id in PAPER_VARIANT_EXPANSION_METHODS:
        record = catalog.mechanisms[method_id]
        assert record.provenance_kind == "paper_variant"
        assert record.deviations
    assert catalog.references["volume_valuation"].repository_url


def test_new_metrics_and_setting_primary_rules_are_catalogued() -> None:
    metrics = load_metric_definitions()

    assert NEW_METRICS <= set(metrics)
    assert SETTING_PRIMARY_METRICS["V-REPLICATION-ROBUSTNESS"] == (
        "replication_owner_rank_change", "minimize"
    )
    assert SETTING_PRIMARY_METRICS["P-MARKET-CONCENTRATION"] == (
        "oracle_ratio", "maximize"
    )
    assert SETTING_PRIMARY_METRICS["T-MARKET-THICKNESS"] == (
        "gain_from_trade_ratio", "maximize"
    )
    assert metrics["replication_owner_rank_change"].ranking_role == "primary"
    assert metrics["replication_reward_share_gain"].ranking_role == "diagnostic"
    assert "replication_reward_share_gain" in metrics[
        "replication_owner_rank_change"
    ].companion_metrics
    assert metrics["normalized_trade_loss"].paper_protocol


def test_expectations_cover_new_paper_claims_without_filtering_results() -> None:
    expectation_ids = {item.expectation_id for item in load_expectations()}

    assert {
        "rvsv-characteristic-inflation",
        "jt-random-tm-approximation",
        "jt-random-eom-approximation",
        "jt-deterministic-eom-approximation",
        "mcafee-thickness-trade-loss",
    } <= expectation_ids


def test_full_config_and_qualification_include_new_settings() -> None:
    config = load_config("benchmark/configs/full.yaml")
    assert "VREP-digits-c4" in config.case_ids["valuation"]
    assert "PCONC-dominant-b5" in config.case_ids["procurement"]
    assert "TTHICK-n16-k12" in config.case_ids["trading"]

    covered = {
        (policy.track, setting)
        for policy in load_qualification_policies()
        for setting in policy.settings
    }
    assert ("procurement", "P-MARKET-CONCENTRATION") in covered
    assert ("trading", "T-MARKET-THICKNESS") in covered


def test_result_metadata_tracks_the_current_metric_catalog_version() -> None:
    config = BenchmarkConfig(
        name="metric-version-check",
        output_dir="unused",
        seeds=(0,),
        methods={
            "valuation": {"shapley_exact": {}},
            "procurement": {},
            "trading": {},
        },
        case_ids={
            "valuation": ("C-add",),
            "procurement": (),
            "trading": (),
        },
    )

    (result,) = run_benchmark(config)

    assert result.metadata["metric_catalog_version"] == "1.2"
