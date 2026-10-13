from __future__ import annotations

import json
from pathlib import Path

import yaml
from datamechbench.independent_validity import audit_independent_validity


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path, *, duplicate: bool = False) -> Path:
    heldout_one = tmp_path / "heldout-one.json"
    heldout_two = tmp_path / "heldout-two.json"
    _write_json(
        heldout_one,
        {"tracks": {"valuation": {"blocks": [{"block_id": "a", "source_uri": "https://example.org/data"}]}}},
    )
    _write_json(
        heldout_two,
        {"tracks": {"valuation": {"blocks": [{"block_id": "b", "source_uri": "https://example.org/data"}]}}},
    )
    record_one = tmp_path / "external-one.json"
    record_two = tmp_path / "external-two.json"
    _write_json(
        record_one,
        {
            "schema_version": "1.0",
            "record_kind": "external_implementation_validation",
            "validation_id": "validation-one",
            "method_id": "m1",
            "track": "valuation",
            "external_implementation": {"repository_url": "https://github.com/org/repo"},
        },
    )
    _write_json(
        record_two,
        {
            "schema_version": "1.0",
            "record_kind": "external_implementation_validation",
            "validation_id": "validation-one" if duplicate else "validation-two",
            "method_id": "m1" if duplicate else "m2",
            "track": "valuation" if duplicate else "trading",
            "external_implementation": {"repository_url": "https://github.com/other/repo"},
        },
    )
    catalog = tmp_path / "target.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "flagships": {
                    "valuation": {"method_ids": ["m1"]},
                    "procurement": {"method_ids": ["m3"]},
                    "trading": {"method_ids": ["m2"]},
                },
                "parity_evidence": {
                    "m1": {"status": "verified"},
                    "m2": {"status": "verified"},
                    "m3": {"status": "missing"},
                },
                "evidence": {
                    "heldout_manifests": [str(heldout_one), str(heldout_two)],
                    "external_validation_records": [str(record_one), str(record_two)],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return catalog


def test_validity_audit_deduplicates_source_uris_and_reports_exact_gaps(tmp_path: Path) -> None:
    report = audit_independent_validity(_fixture(tmp_path), repository_root=tmp_path)

    assert report.valid is True
    assert report.headline_method_count == 3
    assert report.local_parity_verified_count == 2
    assert report.external_record_count == 2
    assert report.external_method_count == 2
    assert report.unique_source_uri_count == 1
    assert report.unique_source_domain_count == 1
    assert report.methods_without_external_validation == ("m3",)
    assert report.tracks_without_external_validation == ("procurement",)


def test_validity_audit_rejects_duplicate_validation_ids(tmp_path: Path) -> None:
    report = audit_independent_validity(
        _fixture(tmp_path, duplicate=True), repository_root=tmp_path
    )

    assert report.valid is False
    assert report.duplicate_validation_ids == ("validation-one",)
