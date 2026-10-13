"""Audit the statistical evidence hierarchy of frozen benchmark blocks."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

OUTPUT_NAMES = ("block_hierarchy.csv", "summary.json")
REQUIRED_FIELDS = (
    "block_id",
    "track",
    "wave",
    "temporal_block_id",
    "dataset_id",
    "source_family_id",
    "institution_id",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_catalog(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported source hierarchy schema_version")
    if not isinstance(payload.get("blocks"), list):
        raise ValueError("source hierarchy blocks must be a list")
    return payload


def _manifest_blocks(paths: Iterable[str | Path]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for track, section in payload.get("tracks", {}).items():
            for block in section.get("blocks", []):
                block_id = str(block.get("block_id", "")).strip()
                if not block_id:
                    raise ValueError(f"manifest block without block_id: {path}")
                if block_id in observed:
                    raise ValueError(f"duplicate manifest block: {block_id}")
                observed[block_id] = str(track)
    return observed


def _claim_status(records: list[Mapping[str, str]], minimum: int) -> str:
    temporal = {row["temporal_block_id"] for row in records}
    datasets = {row["dataset_id"] for row in records}
    sources = {row["source_family_id"] for row in records}
    institutions = {row["institution_id"] for row in records}
    if len(sources) >= minimum and len(institutions) >= minimum:
        return "cross_source_supported"
    if len(datasets) >= 2 and len(sources) >= 2:
        return "multi_dataset_single_institution"
    if len(temporal) >= 2:
        return "temporal_transfer_only"
    return "single_block_only"


def audit_source_hierarchy(
    catalog_path: str | Path,
    manifest_paths: Iterable[str | Path],
) -> dict[str, Any]:
    """Validate one-to-one block mappings and compute defensible claim scope."""

    catalog = _load_catalog(catalog_path)
    observed = _manifest_blocks(manifest_paths)
    rows = catalog["blocks"]
    errors: list[str] = []
    counts = Counter(str(row.get("block_id", "")).strip() for row in rows)
    for block_id, count in sorted(counts.items()):
        if block_id and count > 1:
            errors.append(f"duplicate_mapping:{block_id}")
    mapped = {block_id for block_id in counts if block_id}
    for block_id in sorted(set(observed) - mapped):
        errors.append(f"missing_mapping:{block_id}")
    for block_id in sorted(mapped - set(observed)):
        errors.append(f"unregistered_mapping:{block_id}")

    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        row = {field: str(raw.get(field, "")).strip() for field in REQUIRED_FIELDS}
        missing = [field for field, value in row.items() if not value]
        if missing:
            errors.append(f"missing_fields:{index}:{','.join(missing)}")
            continue
        if row["block_id"] in observed and observed[row["block_id"]] != row["track"]:
            errors.append(f"track_mismatch:{row['block_id']}")
        normalized.append(row)

    minimum = int(catalog.get("cross_source_minimum", 3))
    declared = catalog.get("declared_track_status", {})
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in normalized:
        grouped[row["track"]].append(row)
    tracks: dict[str, Any] = {}
    for track in sorted(grouped):
        records = grouped[track]
        status = _claim_status(records, minimum)
        if declared.get(track) != status:
            errors.append(
                f"declared_status_mismatch:{track}:{declared.get(track)}:{status}"
            )
        tracks[track] = {
            "block_count": len(records),
            "temporal_block_count": len({row["temporal_block_id"] for row in records}),
            "dataset_count": len({row["dataset_id"] for row in records}),
            "source_family_count": len({row["source_family_id"] for row in records}),
            "institution_count": len({row["institution_id"] for row in records}),
            "claim_status": status,
            "cross_source_supported": status == "cross_source_supported",
        }
    return {
        "schema_version": "1.0",
        "study_id": "kdd-source-hierarchy-v1",
        "valid": not errors,
        "errors": errors,
        "cross_source_minimum": minimum,
        "block_count": len(observed),
        "tracks": tracks,
        "claim_boundary": (
            "Temporal blocks, datasets, source families, and institutions are distinct "
            "evidence units; repeated dates never establish cross-source transfer."
        ),
        "records": sorted(normalized, key=lambda row: (row["track"], row["wave"], row["block_id"])),
    }


def build_source_hierarchy_audit(
    output_dir: str | Path,
    *,
    catalog_path: str | Path,
    manifest_paths: Iterable[str | Path],
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifests = tuple(Path(path) for path in manifest_paths)
    report = audit_source_hierarchy(catalog_path, manifests)
    with (output / "block_hierarchy.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(report["records"])
    summary = {key: value for key, value in report.items() if key != "records"}
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    inputs = [Path(catalog_path), *manifests]
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "source_hierarchy_audit",
        "inputs": [{"path": str(path), "sha256": _sha256(path)} for path in inputs],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_source_hierarchy_audit(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    seen: set[str] = set()
    for record in payload.get("outputs", []):
        name = str(record.get("path", ""))
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_output:{name}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
    if seen != set(OUTPUT_NAMES):
        errors.append("output_set_mismatch")
    summary_path = path.parent / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not summary.get("valid", False):
            errors.append("invalid_summary")
    return {"valid": not errors, "errors": errors}


__all__ = [
    "audit_source_hierarchy",
    "build_source_hierarchy_audit",
    "verify_source_hierarchy_audit",
]

