from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from datamechbench.source_hierarchy import (
    audit_source_hierarchy,
    build_source_hierarchy_audit,
    verify_source_hierarchy_audit,
)


def _write_inputs(tmp_path: Path, *, duplicate: bool = False, omit: bool = False) -> tuple[Path, list[Path]]:
    manifest = {
        "tracks": {
            "valuation": {"blocks": [{"block_id": "v-a"}, {"block_id": "v-b"}, {"block_id": "v-c"}]},
            "procurement": {"blocks": [{"block_id": "p-t1"}, {"block_id": "p-t2"}]},
        }
    }
    manifest_path = tmp_path / "wave.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocks = [
        {"block_id": "v-a", "track": "valuation", "wave": "v1", "temporal_block_id": "v-a", "dataset_id": "a", "source_family_id": "a", "institution_id": "ia"},
        {"block_id": "v-b", "track": "valuation", "wave": "v1", "temporal_block_id": "v-b", "dataset_id": "b", "source_family_id": "b", "institution_id": "ib"},
        {"block_id": "v-c", "track": "valuation", "wave": "v1", "temporal_block_id": "v-c", "dataset_id": "c", "source_family_id": "c", "institution_id": "ic"},
        {"block_id": "p-t1", "track": "procurement", "wave": "v1", "temporal_block_id": "p-t1", "dataset_id": "p-2024", "source_family_id": "chile", "institution_id": "chilecompra"},
        {"block_id": "p-t2", "track": "procurement", "wave": "v2", "temporal_block_id": "p-t2", "dataset_id": "p-2024", "source_family_id": "chile", "institution_id": "chilecompra"},
    ]
    if omit:
        blocks = blocks[:-1]
    if duplicate:
        blocks.append(dict(blocks[0]))
    catalog = {
        "schema_version": "1.0",
        "cross_source_minimum": 3,
        "declared_track_status": {
            "valuation": "cross_source_supported",
            "procurement": "temporal_transfer_only",
        },
        "blocks": blocks,
    }
    catalog_path = tmp_path / "hierarchy.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return catalog_path, [manifest_path]


def test_source_hierarchy_distinguishes_temporal_from_cross_source(tmp_path: Path) -> None:
    catalog, manifests = _write_inputs(tmp_path)
    report = audit_source_hierarchy(catalog, manifests)

    assert report["valid"] is True
    assert report["tracks"]["valuation"]["claim_status"] == "cross_source_supported"
    assert report["tracks"]["valuation"]["institution_count"] == 3
    assert report["tracks"]["procurement"]["claim_status"] == "temporal_transfer_only"
    assert report["tracks"]["procurement"]["temporal_block_count"] == 2
    assert report["tracks"]["procurement"]["source_family_count"] == 1


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_source_hierarchy_fails_closed_on_mapping_errors(tmp_path: Path, mode: str) -> None:
    catalog, manifests = _write_inputs(
        tmp_path, duplicate=mode == "duplicate", omit=mode == "missing"
    )
    report = audit_source_hierarchy(catalog, manifests)
    assert report["valid"] is False
    assert any(mode in error for error in report["errors"])


def test_source_hierarchy_builder_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    catalog, manifests = _write_inputs(tmp_path)
    output = tmp_path / "out"
    first = build_source_hierarchy_audit(
        output, catalog_path=catalog, manifest_paths=manifests
    )
    first_bytes = (output / "summary.json").read_bytes()
    second = build_source_hierarchy_audit(
        output, catalog_path=catalog, manifest_paths=manifests
    )

    assert first == second
    assert (output / "summary.json").read_bytes() == first_bytes
    assert verify_source_hierarchy_audit(output / "manifest.json") == {
        "valid": True,
        "errors": [],
    }

