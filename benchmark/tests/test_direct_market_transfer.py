from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from datamechbench.direct_market_transfer import (
    DIRECT_MARKET_METHOD_IDS,
    DIRECT_MARKET_SEEDS,
    audit_direct_market_runs,
    build_direct_market_transfer_artifacts,
    make_direct_market_procurement_cases,
    run_direct_market_transfer,
    summarize_cohort_methods,
    verify_direct_market_transfer_artifacts,
)


@dataclass(frozen=True)
class _AdditiveOwnerGame:
    dataset_id: str
    multiplier: float
    owner_ids: tuple[str, ...] = tuple(f"o{index}" for index in range(8))

    def utility_for_owners(self, owners: tuple[str, ...]) -> float:
        return self.multiplier * sum(int(owner[1:]) + 1 for owner in owners)


def _games(count: int = 3) -> dict[str, _AdditiveOwnerGame]:
    return {
        f"dataset-{index}": _AdditiveOwnerGame(f"dataset-{index}", 1.0 + index)
        for index in range(count)
    }


def _profiles(count: int = 8) -> dict:
    cohorts = []
    for index in range(count):
        costs = {
            f"o{owner}": str(round(0.5 + 0.1 * owner + 0.01 * index, 9))
            for owner in range(8)
        }
        cohorts.append({
            "cohort_id": f"cohort-{index}",
            "platform": f"Market {index}",
            "price_mode": ("subscription", "one-off", "usage-based")[index % 3],
            "source_row_count": 100 + index,
            "reported_costs": costs,
        })
    return {
        "schema_version": "1.0",
        "artifact_kind": "anonymous_direct_data_market_price_profiles",
        "study_id": "test-direct-market",
        "claim_boundaries": {
            "evidence_tier": "exploratory_direct_listing_support",
            "heldout_evidence": False,
            "observed_field": "listed_price",
            "not_observed": ["transaction_price", "reservation_cost"],
            "inference_unit": "descriptive_platform_price_mode_cohort",
            "raw_price_pooling_across_modes": "forbidden",
        },
        "cohorts": cohorts,
    }


def _chile_evidence() -> dict:
    return {
        "tracks": {
            "procurement": {
                "contrasts": [
                    {
                        "contrast_id": "P-CGLR-vs-GPS",
                        "method_a": "cgl_randomized",
                        "method_b": "generalized_proportional_share",
                        "block_effects": {
                            "PHO-chile-may": 0.04,
                            "PHO-chile-jun": -0.02,
                            "PHO-chile-sep": 0.01,
                        },
                    },
                    {
                        "contrast_id": "P-JTDEOM-vs-GPS",
                        "method_a": "jt_deterministic_eom",
                        "method_b": "generalized_proportional_share",
                        "block_effects": {
                            "PHO-chile-may": -0.03,
                            "PHO-chile-jun": -0.01,
                            "PHO-chile-sep": 0.02,
                        },
                    },
                ]
            }
        }
    }


def test_case_generator_crosses_eight_cohorts_three_games_and_two_budgets() -> None:
    cases = make_direct_market_procurement_cases(_games(), _profiles())

    assert len(cases) == 48
    assert len({case.case_id for case in cases}) == 48
    assert {case.metadata["benchmark_setting"] for case in cases} == {
        "P-DIRECT-LISTING-SUPPORT"
    }
    assert {case.metadata["cohort"] for case in cases} == {"exploratory"}
    assert {case.metadata["evidence_scope"] for case in cases} == {
        "direct_data_market_listing_support"
    }
    assert {case.metadata["price_mode"] for case in cases} == {
        "subscription",
        "one-off",
        "usage-based",
    }
    assert {case.metadata["budget_ratio"] for case in cases} == {0.3, 0.5}
    assert all(
        "listing_prices_are_not_reservation_costs" in case.metadata["assumptions"]
        for case in cases
    )


def test_runner_uses_exact_method_seed_panel_and_runtime_free_rows() -> None:
    cases = make_direct_market_procurement_cases(_games(1), _profiles(1))

    rows = run_direct_market_transfer(cases)

    assert len(rows) == 22
    assert {row.method_id for row in rows} == {
        "budget_optimum",
        *DIRECT_MARKET_METHOD_IDS,
    }
    for case in cases:
        panel = [row for row in rows if row.case_id == case.case_id]
        assert [row.seed for row in panel if row.method_id == "cgl_randomized"] == list(
            DIRECT_MARKET_SEEDS
        )
        assert [row.seed for row in panel if row.method_id == "jt_random_eom"] == list(
            DIRECT_MARKET_SEEDS
        )
        assert len([row for row in panel if row.method_id == "budget_optimum"]) == 1
        deterministic = [
            row
            for row in panel
            if row.method_id
            in {
                "generalized_proportional_share",
                "cgl_deterministic",
                "jt_greedy_tm",
                "jt_deterministic_eom",
            }
        ]
        assert len(deterministic) == 4
    assert all(row.status == "completed" for row in rows)
    assert all("runtime" not in row.to_dict() for row in rows)
    assert all(row.oracle_ratio is not None for row in rows)
    assert audit_direct_market_runs(rows, cases) == ()


def test_run_audit_rejects_missing_seed_panel() -> None:
    cases = make_direct_market_procurement_cases(_games(1), _profiles(1))
    rows = run_direct_market_transfer(cases)

    errors = audit_direct_market_runs(rows[:-1], cases)

    assert any(error.startswith("missing_run:") for error in errors)


def test_cohort_summary_keeps_performance_and_constraints_separate() -> None:
    cases = make_direct_market_procurement_cases(_games(1), _profiles(1))
    rows = run_direct_market_transfer(cases)

    summaries = summarize_cohort_methods(rows)

    assert len(summaries) == 6
    gps = next(
        item for item in summaries if item.method_id == "generalized_proportional_share"
    )
    assert gps.cohort_id == "cohort-0"
    assert gps.case_count == 2
    assert gps.run_count == 2
    assert 0 <= gps.macro_oracle_ratio <= 1
    assert 0 <= gps.budget_feasible_rate <= 1
    assert 0 <= gps.seller_ir_pass_rate <= 1
    assert 0 <= gps.payment_complete_rate <= 1


def test_artifact_builder_emits_transfer_findings_and_rebuilds_identically(
    tmp_path: Path,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    chile_path = tmp_path / "chile.json"
    profiles_path.write_text(
        json.dumps(_profiles(1), sort_keys=True), encoding="utf-8"
    )
    chile_path.write_text(
        json.dumps(_chile_evidence(), sort_keys=True), encoding="utf-8"
    )
    output = tmp_path / "study"

    built = build_direct_market_transfer_artifacts(
        _games(1), profiles_path, chile_path, output
    )
    first = {path.name: path.read_bytes() for path in sorted(output.iterdir())}
    rebuilt = build_direct_market_transfer_artifacts(
        _games(1), profiles_path, chile_path, output
    )
    second = {path.name: path.read_bytes() for path in sorted(output.iterdir())}
    verified = verify_direct_market_transfer_artifacts(
        output, profiles_path, chile_path
    )

    assert built["raw_run_count"] == 22
    assert built["cohort_method_count"] == 6
    assert built["transfer_contrast_count"] == 2
    assert rebuilt == built
    assert first == second
    assert verified == {"valid": True, "errors": []}
    findings = json.loads((output / "findings.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert all(
        not Path(record["path"]).is_absolute()
        for record in manifest["inputs"].values()
    )
    assert findings["evidence_tier"] == "exploratory_direct_listing_support"
    assert findings["heldout_evidence"] is False
    assert findings["independent_market_count"] == 0
    assert findings["price_semantics"] == "listed_asks_not_transactions_or_costs"
    assert len(findings["findings"]) >= 2


def test_transfer_report_does_not_promote_listings_to_transactions(
    tmp_path: Path,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    chile_path = tmp_path / "chile.json"
    profiles_path.write_text(json.dumps(_profiles(1)), encoding="utf-8")
    chile_path.write_text(json.dumps(_chile_evidence()), encoding="utf-8")
    output = tmp_path / "study"

    build_direct_market_transfer_artifacts(
        _games(1), profiles_path, chile_path, output
    )
    report = (output / "report.md").read_text(encoding="utf-8")

    assert "listed asks" in report
    assert "not realized transactions or latent reservation costs" in report
    assert "confirmatory evidence" not in report


def test_chile_input_binding_ignores_runtime_but_rejects_contrast_drift(
    tmp_path: Path,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    chile_path = tmp_path / "chile.json"
    profiles_path.write_text(json.dumps(_profiles(1)), encoding="utf-8")
    chile = _chile_evidence()
    chile["runtime_seconds"] = 1.0
    chile_path.write_text(json.dumps(chile, sort_keys=True), encoding="utf-8")
    output = tmp_path / "study"

    build_direct_market_transfer_artifacts(
        _games(1), profiles_path, chile_path, output
    )
    first_manifest = (output / "manifest.json").read_bytes()

    chile["runtime_seconds"] = 99.0
    chile_path.write_text(json.dumps(chile, sort_keys=True), encoding="utf-8")
    assert verify_direct_market_transfer_artifacts(
        output, profiles_path, chile_path
    ) == {"valid": True, "errors": []}
    build_direct_market_transfer_artifacts(
        _games(1), profiles_path, chile_path, output
    )
    assert (output / "manifest.json").read_bytes() == first_manifest

    chile["tracks"]["procurement"]["contrasts"][0]["block_effects"][
        "PHO-chile-may"
    ] = 0.5
    chile_path.write_text(json.dumps(chile, sort_keys=True), encoding="utf-8")
    checked = verify_direct_market_transfer_artifacts(
        output, profiles_path, chile_path
    )
    assert checked["valid"] is False
    assert "input_scientific_hash_mismatch:chile_evidence" in checked["errors"]
