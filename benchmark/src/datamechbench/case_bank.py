"""Strict evidence validation for independent benchmark case banks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import BenchmarkResult

CASE_BANK_TRACKS = ("valuation", "procurement", "trading")
_COHORTS = frozenset({"development", "heldout"})
_INDEPENDENCE_UNITS = frozenset({"base_dataset", "generator_family", "market_source"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CaseBankAudit:
    block_counts: Mapping[str, int]
    generator_counts: Mapping[str, int]
    cohorts: Mapping[str, tuple[str, ...]]
    errors: tuple[str, ...]


def _resolve(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing:{label}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid:{label}:{exc.__class__.__name__}")
        return None
    if not isinstance(payload, Mapping):
        errors.append(f"invalid:{label}:not_object")
        return None
    return {str(key): value for key, value in payload.items()}


def _required_string(
    block: Mapping[str, Any], field: str, prefix: str, errors: list[str]
) -> str:
    value = str(block.get(field, "")).strip()
    if not value:
        errors.append(f"{prefix}:missing_{field}")
    return value


def audit_case_bank_manifests(
    paths: Iterable[str],
    repository_root: str | Path,
    results: Iterable[BenchmarkResult],
) -> CaseBankAudit:
    """Validate explicit blocks and derive counts without trusting declarations."""

    root = Path(repository_root)
    completed: dict[tuple[str, str], set[str]] = {}
    for row in results:
        if row.status != "completed":
            continue
        completed.setdefault((row.track, row.case_id), set()).add(
            str(row.metadata.get("benchmark_setting", ""))
        )

    errors: list[str] = []
    track_errors: dict[str, list[str]] = {track: [] for track in CASE_BANK_TRACKS}
    blocks: dict[str, list[Mapping[str, Any]]] = {track: [] for track in CASE_BANK_TRACKS}
    seen_block_ids: dict[str, set[str]] = {track: set() for track in CASE_BANK_TRACKS}
    seen_cases: dict[str, set[str]] = {track: set() for track in CASE_BANK_TRACKS}
    global_invalid = False

    for raw_path in paths:
        path = _resolve(str(raw_path), root)
        manifest = _read_manifest(path, str(raw_path), errors)
        if manifest is None:
            global_invalid = True
            continue
        if manifest.get("schema_version") != "1.0":
            errors.append(f"invalid:{raw_path}:schema_version")
            global_invalid = True
            continue
        if manifest.get("manifest_kind") != "independent_case_bank":
            errors.append(f"invalid:{raw_path}:manifest_kind")
            global_invalid = True
            continue
        result_record = manifest.get("results")
        if not isinstance(result_record, Mapping):
            errors.append(f"invalid:{raw_path}:results")
            global_invalid = True
            continue
        result_path_raw = str(result_record.get("path", "")).strip()
        expected_hash = str(result_record.get("sha256", "")).strip()
        result_path = _resolve(result_path_raw, root)
        if not result_path_raw or not result_path.is_file():
            errors.append(f"invalid:{raw_path}:missing_results_file")
            global_invalid = True
            continue
        if not _SHA256.fullmatch(expected_hash) or _sha256(result_path) != expected_hash:
            errors.append(f"invalid:{raw_path}:results_sha256_mismatch")
            global_invalid = True
            continue
        track_records = manifest.get("tracks")
        if not isinstance(track_records, Mapping):
            errors.append(f"invalid:{raw_path}:tracks")
            global_invalid = True
            continue

        for track in CASE_BANK_TRACKS:
            item = track_records.get(track)
            if not isinstance(item, Mapping):
                track_errors[track].append(f"invalid:{raw_path}:missing_track:{track}")
                continue
            raw_blocks = item.get("blocks")
            if not isinstance(raw_blocks, list) or not raw_blocks:
                if "independent_blocks" in item or "generator_families" in item:
                    track_errors[track].append(f"invalid:{raw_path}:legacy_count_only:{track}")
                else:
                    track_errors[track].append(f"invalid:{raw_path}:missing_blocks:{track}")
                continue
            for index, raw_block in enumerate(raw_blocks):
                prefix = f"invalid:{raw_path}:{track}:block_{index}"
                if not isinstance(raw_block, Mapping):
                    track_errors[track].append(f"{prefix}:not_object")
                    continue
                block = {str(key): value for key, value in raw_block.items()}
                before = len(track_errors[track])
                block_id = _required_string(block, "block_id", prefix, track_errors[track])
                cohort = _required_string(block, "cohort", prefix, track_errors[track])
                setting_id = _required_string(block, "setting_id", prefix, track_errors[track])
                generator = _required_string(
                    block, "generator_family", prefix, track_errors[track]
                )
                independence = _required_string(
                    block, "independence_unit", prefix, track_errors[track]
                )
                _required_string(block, "source_kind", prefix, track_errors[track])
                _required_string(block, "source_uri", prefix, track_errors[track])
                _required_string(block, "license_id", prefix, track_errors[track])
                input_hash = _required_string(
                    block, "input_hash", prefix, track_errors[track]
                )
                if cohort and cohort not in _COHORTS:
                    track_errors[track].append(f"{prefix}:unsupported_cohort:{cohort}")
                if independence and independence not in _INDEPENDENCE_UNITS:
                    track_errors[track].append(
                        f"{prefix}:unsupported_independence_unit:{independence}"
                    )
                if input_hash and not _SHA256.fullmatch(input_hash):
                    track_errors[track].append(f"{prefix}:invalid_input_hash")
                case_ids = block.get("case_ids")
                if (
                    not isinstance(case_ids, list)
                    or not case_ids
                    or any(not str(case_id).strip() for case_id in case_ids)
                    or len({str(case_id) for case_id in case_ids}) != len(case_ids)
                ):
                    track_errors[track].append(f"{prefix}:invalid_case_ids")
                    case_ids = []
                if block_id in seen_block_ids[track]:
                    track_errors[track].append(f"duplicate_block_id:{track}:{block_id}")
                seen_block_ids[track].add(block_id)
                for raw_case_id in case_ids:
                    case_id = str(raw_case_id)
                    if case_id in seen_cases[track]:
                        track_errors[track].append(f"duplicate_case:{track}:{case_id}")
                    seen_cases[track].add(case_id)
                    observed_settings = completed.get((track, case_id), set())
                    if not observed_settings:
                        track_errors[track].append(
                            f"missing_completed_case:{track}:{case_id}"
                        )
                    elif setting_id not in observed_settings:
                        track_errors[track].append(
                            f"setting_mismatch:{track}:{case_id}:"
                            f"expected={setting_id}:observed={','.join(sorted(observed_settings))}"
                        )
                if len(track_errors[track]) == before:
                    blocks[track].append({
                        "block_id": block_id,
                        "cohort": cohort,
                        "generator_family": generator,
                    })

    for track in CASE_BANK_TRACKS:
        errors.extend(track_errors[track])
    if global_invalid:
        return CaseBankAudit(
            block_counts={track: 0 for track in CASE_BANK_TRACKS},
            generator_counts={track: 0 for track in CASE_BANK_TRACKS},
            cohorts={track: () for track in CASE_BANK_TRACKS},
            errors=tuple(errors),
        )

    block_counts = {
        track: 0 if track_errors[track] else len(blocks[track])
        for track in CASE_BANK_TRACKS
    }
    generator_counts = {
        track: 0 if track_errors[track] else len({
            str(block["generator_family"]) for block in blocks[track]
        })
        for track in CASE_BANK_TRACKS
    }
    cohorts = {
        track: () if track_errors[track] else tuple(sorted({
            str(block["cohort"]) for block in blocks[track]
        }))
        for track in CASE_BANK_TRACKS
    }
    return CaseBankAudit(block_counts, generator_counts, cohorts, tuple(errors))


__all__ = ["CASE_BANK_TRACKS", "CaseBankAudit", "audit_case_bank_manifests"]
