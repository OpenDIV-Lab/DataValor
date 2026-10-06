from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import pytest
from datamechbench.direct_market_calibration import (
    audit_dadada_profiles,
    build_calibration_artifacts,
    build_dadada_profiles,
    verify_calibration_artifacts,
)

FIELDS = (
    "category",
    "coverage",
    "data_sample",
    "description",
    "dimension",
    "platform",
    "price",
    "price_mode",
    "provider",
    "size",
    "title",
    "update_frequency",
    "url",
    "volume",
)


def _write_fixture(path: Path, *, malformed: bool = False, short: bool = False) -> str:
    rows = []
    cohort_specs = (
        ("Market A", "subscription", range(1, 9)),
        ("Market B", "one-off", range(2, 10)),
    )
    for platform, mode, exponents in cohort_specs:
        values = list(exponents)
        if short and platform == "Market B":
            values.pop()
        for index, exponent in enumerate(values):
            price = math.exp(exponent) - 1
            if malformed and platform == "Market A" and index == 0:
                price = "not-a-price"
            rows.append({
                "category": "Financial Services Data",
                "coverage": "sentinel-country",
                "data_sample": "sentinel-sample.csv",
                "description": "sentinel-description",
                "dimension": "4",
                "platform": platform,
                "price": str(price),
                "price_mode": mode,
                "provider": "sentinel-provider",
                "size": "10",
                "title": "sentinel-title",
                "update_frequency": "daily",
                "url": "https://example.invalid/sentinel",
                "volume": "20",
            })
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol(raw_sha256: str, *, row_count: int = 16) -> dict:
    return {
        "schema_version": "1.0",
        "study_id": "test-dadada",
        "source": {
            "repository": "https://github.com/ZJU-DIVER/DaDaDa",
            "commit": "a" * 40,
            "commit_date": "2026-01-30T10:42:20Z",
            "data_path": "DaDaDa/data/final_data.csv",
            "data_url": "https://example.invalid/final_data.csv",
            "expected_sha256": raw_sha256,
            "expected_row_count": row_count,
            "license_id": "Apache-2.0",
            "license_url": "https://example.invalid/LICENSE",
            "license_sha256": "b" * 64,
        },
        "transformation": {
            "explicit_price_modes": ["subscription", "one-off", "usage-based"],
            "minimum_cohort_size": 8,
            "seller_count": 8,
            "winsor_quantiles": [0.0, 1.0],
            "price_transform": "winsorize_then_log1p_then_divide_by_selected_median",
            "identity_policy": "retain_only_platform_mode_counts_statistics_and_anonymous_quantiles",
        },
        "cohorts": [
            {
                "cohort_id": "market-a--subscription",
                "platform": "Market A",
                "price_mode": "subscription",
                "expected_row_count": 8,
            },
            {
                "cohort_id": "market-b--one-off",
                "platform": "Market B",
                "price_mode": "one-off",
                "expected_row_count": 8,
            },
        ],
        "claim_boundaries": {
            "evidence_tier": "exploratory_direct_listing_support",
            "heldout_evidence": False,
            "observed_field": "listed_price",
            "not_observed": ["transaction_price", "reservation_cost"],
        },
    }


def test_build_profiles_separates_modes_and_matches_hand_derived_quantiles(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw))

    payload = build_dadada_profiles(raw, protocol)

    assert payload["source_row_count"] == 16
    assert payload["eligible_explicit_price_row_count"] == 16
    assert [item["cohort_id"] for item in payload["cohorts"]] == [
        "market-a--subscription",
        "market-b--one-off",
    ]
    first = payload["cohorts"][0]
    assert first["source_row_count"] == 8
    assert first["reported_costs"] == {
        "o0": "0.319444444",
        "o1": "0.513888889",
        "o2": "0.708333333",
        "o3": "0.902777778",
        "o4": "1.097222222",
        "o5": "1.291666667",
        "o6": "1.486111111",
        "o7": "1.680555556",
    }
    assert first["raw_price_statistics"]["median"] == pytest.approx(
        (math.exp(4) - 1 + math.exp(5) - 1) / 2
    )
    assert audit_dadada_profiles(payload, protocol) == ()


def test_processed_profiles_do_not_retain_listing_identity_fields(tmp_path: Path) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw))

    serialized = json.dumps(build_dadada_profiles(raw, protocol), sort_keys=True)

    for forbidden in (
        "sentinel-title",
        "sentinel-provider",
        "sentinel-description",
        "sentinel-country",
        "sentinel-sample.csv",
        "example.invalid/sentinel",
    ):
        assert forbidden not in serialized


def test_build_profiles_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    raw = tmp_path / "fixture.csv"
    _write_fixture(raw)

    with pytest.raises(ValueError, match="source SHA-256 mismatch"):
        build_dadada_profiles(raw, _protocol("0" * 64))


def test_build_profiles_rejects_malformed_price(tmp_path: Path) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw, malformed=True))

    with pytest.raises(ValueError, match="invalid price"):
        build_dadada_profiles(raw, protocol)


def test_build_profiles_rejects_ineligible_frozen_cohort(tmp_path: Path) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw, short=True), row_count=15)
    protocol["cohorts"][1]["expected_row_count"] = 7

    with pytest.raises(ValueError, match="below minimum cohort size"):
        build_dadada_profiles(raw, protocol)


def test_profile_audit_rejects_duplicate_ids_and_forbidden_fields(tmp_path: Path) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw))
    payload = build_dadada_profiles(raw, protocol)
    payload["cohorts"].append(dict(payload["cohorts"][0]))
    payload["cohorts"][0]["title"] = "identity leak"

    errors = audit_dadada_profiles(payload, protocol)

    assert "duplicate_cohort_id:market-a--subscription" in errors
    assert "forbidden_identity_field:title" in errors


def test_artifact_build_and_verify_do_not_require_raw_csv_after_build(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "fixture.csv"
    protocol = _protocol(_write_fixture(raw))
    output = tmp_path / "output"

    built = build_calibration_artifacts(raw, output, protocol)
    first_bytes = {
        path.name: path.read_bytes() for path in sorted(output.iterdir())
    }
    raw.unlink()

    verified = verify_calibration_artifacts(output, protocol)

    assert built["cohort_count"] == 2
    assert built["source_row_count"] == 16
    assert verified == {"valid": True, "errors": []}
    assert first_bytes == {
        path.name: path.read_bytes() for path in sorted(output.iterdir())
    }
