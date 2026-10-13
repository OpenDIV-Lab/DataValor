"""Inventory independent validity evidence without upgrading evidence tiers."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

OUTPUT_NAMES = ("method_coverage.csv", "source_inventory.csv", "gaps.json", "summary.json")


@dataclass(frozen=True)
class IndependentValidityReport:
    valid: bool
    headline_method_count: int
    local_parity_verified_count: int
    external_record_count: int
    external_method_count: int
    external_repository_count: int
    external_track_count: int
    unique_source_uri_count: int
    unique_source_domain_count: int
    methods_without_external_validation: tuple[str, ...]
    tracks_without_external_validation: tuple[str, ...]
    duplicate_validation_ids: tuple[str, ...]
    method_rows: tuple[Mapping[str, Any], ...]
    source_rows: tuple[Mapping[str, Any], ...]


def _resolve(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def audit_independent_validity(
    catalog_path: str | Path,
    *,
    repository_root: str | Path,
) -> IndependentValidityReport:
    """Audit local parity, external comparisons, and held-out source diversity."""

    root = Path(repository_root)
    source = Path(catalog_path)
    if not source.is_absolute():
        source = root / source
    catalog = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    flagships = catalog.get("flagships", {})
    method_track = {
        str(method): str(track)
        for track, item in flagships.items()
        for method in item.get("method_ids", [])
    }
    parity = catalog.get("parity_evidence", {})
    evidence = catalog.get("evidence", {})

    records: list[Mapping[str, Any]] = []
    for record_path in evidence.get("external_validation_records", []):
        payload = json.loads(_resolve(str(record_path), root).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"external record is not an object: {record_path}")
        records.append(payload)
    validation_ids = [str(record.get("validation_id", "")) for record in records]
    duplicate_ids = tuple(
        sorted(key for key, count in Counter(validation_ids).items() if key and count > 1)
    )
    external_methods = {str(record.get("method_id", "")) for record in records}
    external_methods.discard("")
    external_tracks = {str(record.get("track", "")) for record in records}
    external_tracks.discard("")
    repositories = {
        str(record.get("external_implementation", {}).get("repository_url", ""))
        for record in records
        if isinstance(record.get("external_implementation"), Mapping)
    }
    repositories.discard("")

    source_rows: list[Mapping[str, Any]] = []
    for manifest_path in evidence.get("heldout_manifests", []):
        manifest = json.loads(_resolve(str(manifest_path), root).read_text(encoding="utf-8"))
        wave = str(manifest.get("replication_wave", "unknown"))
        for track, item in manifest.get("tracks", {}).items():
            for block in item.get("blocks", []):
                uri = str(block.get("source_uri", "")).strip()
                source_rows.append(
                    {
                        "wave": wave,
                        "track": str(track),
                        "block_id": str(block.get("block_id", "")),
                        "source_uri": uri,
                        "source_domain": urlsplit(uri).netloc.lower(),
                    }
                )
    unique_uris = {str(row["source_uri"]) for row in source_rows if row["source_uri"]}
    unique_domains = {
        str(row["source_domain"]) for row in source_rows if row["source_domain"]
    }
    method_rows = tuple(
        {
            "track": track,
            "method_id": method,
            "local_parity_status": str(parity.get(method, {}).get("status", "missing")),
            "external_validation_record_count": sum(
                str(record.get("method_id", "")) == method for record in records
            ),
            "external_repository_count": len(
                {
                    str(record.get("external_implementation", {}).get("repository_url", ""))
                    for record in records
                    if str(record.get("method_id", "")) == method
                    and isinstance(record.get("external_implementation"), Mapping)
                }
                - {""}
            ),
        }
        for method, track in sorted(method_track.items(), key=lambda item: (item[1], item[0]))
    )
    malformed = any(
        record.get("schema_version") != "1.0"
        or record.get("record_kind") != "external_implementation_validation"
        or not str(record.get("validation_id", ""))
        or str(record.get("method_id", "")) not in method_track
        for record in records
    )
    all_tracks = set(flagships)
    return IndependentValidityReport(
        valid=not duplicate_ids and not malformed,
        headline_method_count=len(method_track),
        local_parity_verified_count=sum(
            row["local_parity_status"] == "verified" for row in method_rows
        ),
        external_record_count=len(records),
        external_method_count=len(external_methods),
        external_repository_count=len(repositories),
        external_track_count=len(external_tracks),
        unique_source_uri_count=len(unique_uris),
        unique_source_domain_count=len(unique_domains),
        methods_without_external_validation=tuple(sorted(set(method_track) - external_methods)),
        tracks_without_external_validation=tuple(sorted(all_tracks - external_tracks)),
        duplicate_validation_ids=duplicate_ids,
        method_rows=method_rows,
        source_rows=tuple(source_rows),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_independent_validity(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    catalog_path: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = audit_independent_validity(catalog_path, repository_root=repository_root)
    with (output / "method_coverage.csv").open("w", encoding="utf-8", newline="") as stream:
        columns = (
            "track", "method_id", "local_parity_status",
            "external_validation_record_count", "external_repository_count",
        )
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(report.method_rows)
    with (output / "source_inventory.csv").open("w", encoding="utf-8", newline="") as stream:
        columns = ("wave", "track", "block_id", "source_uri", "source_domain")
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(report.source_rows)
    gaps = {
        "methods_without_external_validation": list(report.methods_without_external_validation),
        "tracks_without_external_validation": list(report.tracks_without_external_validation),
        "duplicate_validation_ids": list(report.duplicate_validation_ids),
    }
    (output / "gaps.json").write_text(
        json.dumps(gaps, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        key: value
        for key, value in vars(report).items()
        if key not in {"method_rows", "source_rows"}
    }
    summary.update(
        {
            "schema_version": "1.0",
            "study_id": "kdd-independent-validity-v1",
            "methods_without_external_validation": list(
                report.methods_without_external_validation
            ),
            "tracks_without_external_validation": list(
                report.tracks_without_external_validation
            ),
            "duplicate_validation_ids": list(report.duplicate_validation_ids),
            "claim_boundary": (
                "Local parity and external implementation comparison are separate tiers; "
                "uncovered methods and tracks remain explicit gaps."
            ),
        }
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    root = Path(repository_root)
    catalog = Path(catalog_path)
    if not catalog.is_absolute():
        catalog = root / catalog
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "independent_validity",
        "inputs": [{"path": str(catalog_path), "sha256": _sha256(catalog)}],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_independent_validity(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    errors: list[str] = []
    seen: set[str] = set()
    for record in payload.get("outputs", []):
        name = str(record.get("path", ""))
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_or_invalid:{name}")
        elif _sha256(target) != str(record.get("sha256", "")):
            errors.append(f"hash_mismatch:{name}")
    errors.extend(f"missing_binding:{name}" for name in sorted(set(OUTPUT_NAMES) - seen))
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "IndependentValidityReport",
    "audit_independent_validity",
    "build_independent_validity",
    "verify_independent_validity",
]
