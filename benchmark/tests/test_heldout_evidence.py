from __future__ import annotations

import hashlib
import json
from pathlib import Path

from datamechbench.heldout_evidence import audit_heldout_manifests

TARGETS = {
    "valuation": {
        "setting_id": "V-HOLDOUT",
        "method_ids": ("v1", "v2"),
    },
    "procurement": {
        "setting_id": "P-HOLDOUT",
        "method_ids": ("p1", "p2"),
    },
    "trading": {
        "setting_id": "T-HOLDOUT",
        "method_ids": ("t1", "t2"),
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_protocol(tmp_path: Path) -> Path:
    payload = {
        "schema_version": "1.0",
        "manifest_kind": "confirmatory_protocol",
        "sources": ["frozen-source"],
        "transformations": {"winsorization": [0.025, 0.975]},
        "contrasts": ["primary"],
        "confirmatory_outcomes": None,
    }
    payload["protocol_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_results(tmp_path: Path, *, omit: tuple[str, str] | None = None) -> Path:
    rows = []
    for track, target in TARGETS.items():
        for block in range(3):
            case_id = f"{track}-heldout-{block}"
            for method_id in target["method_ids"]:
                if omit == (case_id, method_id):
                    continue
                rows.append({
                    "schema_version": "1.1",
                    "run_id": f"{case_id}-{method_id}",
                    "track": track,
                    "method_id": method_id,
                    "case_id": case_id,
                    "seed": 0,
                    "status": "completed",
                    "metrics": {},
                    "runtime_seconds": 0.0,
                    "metadata": {"benchmark_setting": target["setting_id"]},
                    "error": None,
                })
    path = tmp_path / "heldout-results.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _block(tmp_path: Path, track: str, index: int) -> dict:
    source = tmp_path / f"{track}-source-{index}.json"
    processed = tmp_path / f"{track}-processed-{index}.json"
    source.write_text(json.dumps({"raw": [track, index]}), encoding="utf-8")
    processed.write_text(json.dumps({"types": [index, index + 1]}), encoding="utf-8")
    economic_observables = {
        "valuation": {
            "semantic": "task_utility",
            "observed_measure": "held-out predictive utility",
            "benchmark_role": "coalition utility",
            "claims_supported": ["task_utility"],
            "claims_forbidden": [
                "listing_ask",
                "transaction_price",
                "reservation_value",
                "buyer_value",
            ],
        },
        "procurement": {
            "semantic": "proxy",
            "observed_measure": "public award amount",
            "benchmark_role": "seller-cost shape calibration",
            "claims_supported": ["proxy_calibration"],
            "claims_forbidden": [
                "listing_ask",
                "transaction_price",
                "reservation_value",
                "buyer_value",
            ],
        },
        "trading": {
            "semantic": "proxy",
            "observed_measure": "submitted bid or offer",
            "benchmark_role": "private-type shape calibration",
            "claims_supported": ["proxy_calibration"],
            "claims_forbidden": [
                "listing_ask",
                "transaction_price",
                "reservation_value",
                "buyer_value",
            ],
        },
    }
    return {
        "block_id": f"{track}-source-{index}",
        "source_kind": "open_dataset" if track == "valuation" else "market_calibrated",
        "source_uri": f"https://example.test/{track}/{index}",
        "license_id": "CC-BY-4.0",
        "source_artifact": {"path": str(source), "sha256": _sha(source)},
        "processed_artifact": {"path": str(processed), "sha256": _sha(processed)},
        "case_ids": [f"{track}-heldout-{index}"],
        "economic_observable": economic_observables[track],
        "realism": {
            dimension: {
                "evidence": f"{dimension} evidence",
                "limitation": f"{dimension} limitation",
            }
            for dimension in ("data", "utility", "participant_type", "institutional")
        },
    }


def _valid_manifest(tmp_path: Path, results: Path, protocol: Path) -> dict:
    protocol_payload = json.loads(protocol.read_text(encoding="utf-8"))
    tracks = {}
    for track, target in TARGETS.items():
        tracks[track] = {
            "setting_id": target["setting_id"],
            "blocks": [_block(tmp_path, track, index) for index in range(3)],
            "representativeness": {
                "metrics": [
                    {"name": "wasserstein", "value": 0.2, "reference": "development"}
                ],
                "coverage": 1.0,
                "limitations": "Cross-domain calibration does not identify private values.",
            },
            "contrasts": [{
                "contrast_id": f"{track}-primary",
                "inference_unit": "independent_block",
                "metric": "primary_metric",
                "estimand": "mean_oriented_difference",
                "ci_method": "percentile_block_bootstrap",
                "multiplicity_family": track,
                "decision": "confirmed",
                "effect": 0.1,
                "ci_low": 0.01,
                "ci_high": 0.2,
                "worst_block": f"{track}-source-0",
            }],
        }
    return {
        "schema_version": "1.0",
        "manifest_kind": "confirmatory_evidence",
        "cohort": "heldout",
        "evidence_scope": "real_trained_game",
        "protocol": {
            "path": str(protocol),
            "sha256": _sha(protocol),
            "protocol_hash": protocol_payload["protocol_hash"],
        },
        "results": {"path": str(results), "sha256": _sha(results)},
        "tracks": tracks,
    }


def _audit(tmp_path: Path, manifest: dict, *, development_cases: set[str] | None = None):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return audit_heldout_manifests(
        (str(path),),
        tmp_path,
        TARGETS,
        development_case_ids=development_cases or set(),
        minimum_blocks_per_track=3,
        required_scope="real_trained_game",
    )


def test_valid_explicit_evidence_derives_track_and_block_coverage(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    audit = _audit(tmp_path, _valid_manifest(tmp_path, results, protocol))

    assert audit.errors == ()
    assert audit.covered_tracks == ("procurement", "trading", "valuation")
    assert audit.block_counts == {track: 3 for track in TARGETS}
    assert audit.economic_semantic_counts == {
        "valuation": {
            "task_utility": 3,
            "proxy": 0,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
        "procurement": {
            "task_utility": 0,
            "proxy": 3,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
        "trading": {
            "task_utility": 0,
            "proxy": 3,
            "listing_ask": 0,
            "settlement": 0,
            "elicited_reservation": 0,
        },
    }
    assert audit.economic_claim_support_counts == {
        "task_utility": 3,
        "proxy_calibration": 6,
        "listing_ask": 0,
        "transaction_price": 0,
        "reservation_value": 0,
        "buyer_value": 0,
    }
    assert audit.unique_source_uri_counts == {track: 3 for track in TARGETS}
    assert audit.license_counts == {"CC-BY-4.0": 9}


def test_legacy_track_list_is_rejected(tmp_path: Path) -> None:
    audit = _audit(tmp_path, {
        "cohort": "heldout",
        "evidence_scope": "real_trained_game",
        "tracks": list(TARGETS),
    })

    assert audit.covered_tracks == ()
    assert any("schema_version" in error or "manifest_kind" in error for error in audit.errors)


def test_protocol_and_result_hashes_are_verified(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)
    manifest["protocol"]["sha256"] = "0" * 64
    manifest["results"]["sha256"] = "1" * 64

    audit = _audit(tmp_path, manifest)

    assert any("protocol:sha256_mismatch" in error for error in audit.errors)
    assert any("results:sha256_mismatch" in error for error in audit.errors)


def test_development_case_overlap_is_rejected(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)

    audit = _audit(tmp_path, manifest, development_cases={"valuation-heldout-0"})

    assert any("development_case_overlap:valuation-heldout-0" in error for error in audit.errors)
    assert "valuation" not in audit.covered_tracks


def test_all_realism_dimensions_require_evidence_and_limitation(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)
    del manifest["tracks"]["procurement"]["blocks"][0]["realism"]["institutional"]

    audit = _audit(tmp_path, manifest)

    assert any("missing_realism:institutional" in error for error in audit.errors)
    assert "procurement" not in audit.covered_tracks


def test_missing_economic_observable_contract_is_rejected(tmp_path: Path) -> None:
    """Catch a source block whose price semantics can no longer be audited."""

    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)
    del manifest["tracks"]["procurement"]["blocks"][0]["economic_observable"]

    audit = _audit(tmp_path, manifest)

    assert any("missing_economic_observable" in error for error in audit.errors)
    assert "procurement" not in audit.covered_tracks


def test_listing_ask_cannot_claim_observed_transaction_price(tmp_path: Path) -> None:
    """Catch the construct-invalid inference that an asking price was paid."""

    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)
    contract = manifest["tracks"]["trading"]["blocks"][0]["economic_observable"]
    contract["semantic"] = "listing_ask"
    contract["claims_supported"] = ["transaction_price"]
    contract["claims_forbidden"] = ["reservation_value", "buyer_value"]

    audit = _audit(tmp_path, manifest)

    assert any(
        "unsupported_economic_claim:listing_ask:transaction_price" in error
        for error in audit.errors
    )
    assert "trading" not in audit.covered_tracks


def test_row_level_inference_is_rejected(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path)
    manifest = _valid_manifest(tmp_path, results, protocol)
    manifest["tracks"]["trading"]["contrasts"][0]["inference_unit"] = "run"

    audit = _audit(tmp_path, manifest)

    assert any("invalid_inference_unit" in error for error in audit.errors)
    assert "trading" not in audit.covered_tracks


def test_every_headline_method_must_complete_every_declared_case(tmp_path: Path) -> None:
    protocol = _write_protocol(tmp_path)
    results = _write_results(tmp_path, omit=("valuation-heldout-1", "v2"))
    manifest = _valid_manifest(tmp_path, results, protocol)

    audit = _audit(tmp_path, manifest)

    assert any("missing_headline_result:valuation-heldout-1:v2" in error for error in audit.errors)
    assert "valuation" not in audit.covered_tracks
