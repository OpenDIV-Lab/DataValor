"""Fail-closed audit for confirmatory held-out benchmark evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

HELDOUT_TRACKS = ("valuation", "procurement", "trading")
REALISM_DIMENSIONS = ("data", "utility", "participant_type", "institutional")
ECONOMIC_OBSERVABLE_SEMANTICS = (
    "task_utility",
    "proxy",
    "listing_ask",
    "settlement",
    "elicited_reservation",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECISIONS = frozenset({"confirmed", "boundary", "discrepant", "not_auditable"})
_ECONOMIC_CLAIMS = frozenset({
    "task_utility",
    "proxy_calibration",
    "listing_ask",
    "transaction_price",
    "reservation_value",
    "buyer_value",
})
_SUPPORTED_CLAIMS = {
    "task_utility": frozenset({"task_utility"}),
    "proxy": frozenset({"proxy_calibration"}),
    "listing_ask": frozenset({"listing_ask"}),
    "settlement": frozenset({"transaction_price"}),
    "elicited_reservation": frozenset({"reservation_value"}),
}
_REQUIRED_FORBIDDEN_CLAIMS = {
    "task_utility": frozenset({
        "listing_ask", "transaction_price", "reservation_value", "buyer_value",
    }),
    "proxy": frozenset({
        "listing_ask", "transaction_price", "reservation_value", "buyer_value",
    }),
    "listing_ask": frozenset({
        "transaction_price", "reservation_value", "buyer_value",
    }),
    "settlement": frozenset({"reservation_value", "buyer_value"}),
    "elicited_reservation": frozenset({"transaction_price", "buyer_value"}),
}


@dataclass(frozen=True)
class HeldoutEvidenceAudit:
    covered_tracks: tuple[str, ...]
    block_counts: Mapping[str, int]
    economic_semantic_counts: Mapping[str, Mapping[str, int]]
    economic_claim_support_counts: Mapping[str, int]
    unique_source_uri_counts: Mapping[str, int]
    license_counts: Mapping[str, int]
    errors: tuple[str, ...]


def _resolve(raw_path: str, root: Path) -> Path:
    candidate = Path(raw_path)
    return candidate if candidate.is_absolute() else root / candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing:{label}")
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid:{label}:{exc.__class__.__name__}")
        return None
    if not isinstance(raw, Mapping):
        errors.append(f"invalid:{label}:not_object")
        return None
    return {str(key): value for key, value in raw.items()}


def _artifact(
    raw: Any,
    root: Path,
    prefix: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(raw, Mapping):
        errors.append(f"{prefix}:missing_artifact")
        return None
    raw_path = str(raw.get("path", "")).strip()
    expected = str(raw.get("sha256", "")).strip()
    if not raw_path:
        errors.append(f"{prefix}:missing_path")
        return None
    path = _resolve(raw_path, root)
    if not path.is_file():
        errors.append(f"{prefix}:missing_file:{raw_path}")
        return None
    if not _SHA256.fullmatch(expected) or _sha256(path) != expected:
        errors.append(f"{prefix}:sha256_mismatch")
        return None
    return path


def _target_field(target: Any, field: str) -> Any:
    return target.get(field) if isinstance(target, Mapping) else getattr(target, field)


def _economic_observable(raw: Any, prefix: str, errors: list[str]) -> None:
    """Reject missing or construct-invalid economic-observable claims."""

    if not isinstance(raw, Mapping):
        errors.append(f"{prefix}:missing_economic_observable")
        return
    semantic = str(raw.get("semantic", "")).strip()
    if semantic not in ECONOMIC_OBSERVABLE_SEMANTICS:
        errors.append(f"{prefix}:invalid_economic_semantic:{semantic or 'missing'}")
        return
    for field in ("observed_measure", "benchmark_role"):
        if not str(raw.get(field, "")).strip():
            errors.append(f"{prefix}:missing_economic_{field}")
    claim_sets: dict[str, set[str]] = {}
    for field in ("claims_supported", "claims_forbidden"):
        values = raw.get(field)
        if not isinstance(values, list) or not values:
            errors.append(f"{prefix}:invalid_economic_{field}")
            claim_sets[field] = set()
            continue
        claims = {str(value).strip() for value in values}
        if "" in claims or len(claims) != len(values) or not claims <= _ECONOMIC_CLAIMS:
            errors.append(f"{prefix}:invalid_economic_{field}")
        claim_sets[field] = claims
    supported = claim_sets.get("claims_supported", set())
    forbidden = claim_sets.get("claims_forbidden", set())
    for claim in sorted(supported - _SUPPORTED_CLAIMS[semantic]):
        errors.append(f"{prefix}:unsupported_economic_claim:{semantic}:{claim}")
    for claim in sorted(_REQUIRED_FORBIDDEN_CLAIMS[semantic] - forbidden):
        errors.append(f"{prefix}:missing_forbidden_economic_claim:{semantic}:{claim}")
    for claim in sorted(supported & forbidden):
        errors.append(f"{prefix}:conflicting_economic_claim:{claim}")


def economic_observable_errors(
    raw: Any, prefix: str = "economic_observable"
) -> tuple[str, ...]:
    """Return the shared construct-validity errors for one observable record."""

    errors: list[str] = []
    _economic_observable(raw, prefix, errors)
    return tuple(errors)


def _load_result_index(path: Path, errors: list[str]) -> dict[tuple[str, str], dict[str, set[str]]]:
    index: dict[tuple[str, str], dict[str, set[str]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"results:read_error:{exc.__class__.__name__}")
        return index
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"results:invalid_json_line:{line_number}")
            continue
        if not isinstance(row, Mapping):
            errors.append(f"results:not_object_line:{line_number}")
            continue
        if row.get("status") != "completed":
            continue
        track = str(row.get("track", ""))
        case_id = str(row.get("case_id", ""))
        method_id = str(row.get("method_id", ""))
        metadata = row.get("metadata", {})
        setting = str(metadata.get("benchmark_setting", "")) if isinstance(metadata, Mapping) else ""
        cell = index.setdefault((track, case_id), {"methods": set(), "settings": set()})
        cell["methods"].add(method_id)
        cell["settings"].add(setting)
    return index


def audit_heldout_manifests(
    paths: Iterable[str],
    repository_root: str | Path,
    flagship_targets: Mapping[str, Any],
    *,
    development_case_ids: set[str],
    minimum_blocks_per_track: int,
    required_scope: str,
) -> HeldoutEvidenceAudit:
    """Derive held-out coverage from explicit artifacts and completed rows."""

    root = Path(repository_root)
    errors: list[str] = []
    track_errors: dict[str, list[str]] = {track: [] for track in HELDOUT_TRACKS}
    block_ids: dict[str, set[str]] = {track: set() for track in HELDOUT_TRACKS}
    case_ids: dict[str, set[str]] = {track: set() for track in HELDOUT_TRACKS}
    semantic_counts = {
        track: {semantic: 0 for semantic in ECONOMIC_OBSERVABLE_SEMANTICS}
        for track in HELDOUT_TRACKS
    }
    claim_support_counts = {claim: 0 for claim in sorted(_ECONOMIC_CLAIMS)}
    source_uris: dict[str, set[str]] = {track: set() for track in HELDOUT_TRACKS}
    license_counts: dict[str, int] = {}
    global_invalid = False

    for raw_manifest_path in paths:
        manifest_path = _resolve(str(raw_manifest_path), root)
        manifest = _read_json(manifest_path, str(raw_manifest_path), errors)
        if manifest is None:
            global_invalid = True
            continue
        if manifest.get("schema_version") != "1.0":
            errors.append(f"invalid:{raw_manifest_path}:schema_version")
            global_invalid = True
        if manifest.get("manifest_kind") != "confirmatory_evidence":
            errors.append(f"invalid:{raw_manifest_path}:manifest_kind")
            global_invalid = True
        if manifest.get("cohort") != "heldout":
            errors.append(f"invalid:{raw_manifest_path}:cohort")
            global_invalid = True
        if manifest.get("evidence_scope") != required_scope:
            errors.append(f"invalid:{raw_manifest_path}:evidence_scope")
            global_invalid = True
        if global_invalid:
            continue

        protocol_record = manifest.get("protocol")
        protocol_path = _artifact(
            protocol_record, root, f"invalid:{raw_manifest_path}:protocol", errors
        )
        results_path = _artifact(
            manifest.get("results"), root, f"invalid:{raw_manifest_path}:results", errors
        )
        if protocol_path is None:
            global_invalid = True
        if results_path is None:
            global_invalid = True
        if global_invalid:
            continue

        protocol_errors: list[str] = []
        protocol = _read_json(protocol_path, "protocol", protocol_errors)
        if protocol is None:
            errors.extend(protocol_errors)
            global_invalid = True
            continue
        stored_protocol_hash = str(protocol.get("protocol_hash", ""))
        hash_payload = dict(protocol)
        hash_payload.pop("protocol_hash", None)
        declared_protocol_hash = (
            str(protocol_record.get("protocol_hash", ""))
            if isinstance(protocol_record, Mapping)
            else ""
        )
        if (
            not _SHA256.fullmatch(stored_protocol_hash)
            or stored_protocol_hash != _canonical_hash(hash_payload)
            or declared_protocol_hash != stored_protocol_hash
        ):
            errors.append(f"invalid:{raw_manifest_path}:protocol_hash_mismatch")
            global_invalid = True
            continue
        if protocol.get("confirmatory_outcomes") is not None:
            errors.append(f"invalid:{raw_manifest_path}:protocol_contains_outcomes")
            global_invalid = True
            continue

        result_errors: list[str] = []
        result_index = _load_result_index(results_path, result_errors)
        if result_errors:
            errors.extend(result_errors)
            global_invalid = True
            continue
        tracks = manifest.get("tracks")
        if not isinstance(tracks, Mapping):
            errors.append(f"invalid:{raw_manifest_path}:tracks_not_mapping")
            global_invalid = True
            continue

        for track in HELDOUT_TRACKS:
            prefix = f"invalid:{raw_manifest_path}:{track}"
            target = flagship_targets.get(track)
            item = tracks.get(track)
            if target is None or not isinstance(item, Mapping):
                track_errors[track].append(f"{prefix}:missing_track")
                continue
            setting_id = str(item.get("setting_id", ""))
            expected_setting = str(_target_field(target, "setting_id"))
            if not setting_id or setting_id != expected_setting:
                track_errors[track].append(
                    f"{prefix}:setting_mismatch:expected={expected_setting}:observed={setting_id}"
                )
            blocks = item.get("blocks")
            if not isinstance(blocks, list) or not blocks:
                track_errors[track].append(f"{prefix}:missing_blocks")
                continue
            for block_index, raw_block in enumerate(blocks):
                block_prefix = f"{prefix}:block_{block_index}"
                if not isinstance(raw_block, Mapping):
                    track_errors[track].append(f"{block_prefix}:not_object")
                    continue
                error_count_before_block = len(track_errors[track])
                block = {str(key): value for key, value in raw_block.items()}
                block_id = str(block.get("block_id", "")).strip()
                if not block_id:
                    track_errors[track].append(f"{block_prefix}:missing_block_id")
                elif block_id in block_ids[track]:
                    track_errors[track].append(f"{block_prefix}:duplicate_block_id:{block_id}")
                block_ids[track].add(block_id)
                for field in ("source_kind", "source_uri", "license_id"):
                    if not str(block.get(field, "")).strip():
                        track_errors[track].append(f"{block_prefix}:missing_{field}")
                _artifact(
                    block.get("source_artifact"), root,
                    f"{block_prefix}:source_artifact", track_errors[track]
                )
                _artifact(
                    block.get("processed_artifact"), root,
                    f"{block_prefix}:processed_artifact", track_errors[track]
                )
                _economic_observable(
                    block.get("economic_observable"), block_prefix, track_errors[track]
                )
                realism = block.get("realism")
                for dimension in REALISM_DIMENSIONS:
                    dimension_record = realism.get(dimension) if isinstance(realism, Mapping) else None
                    if not isinstance(dimension_record, Mapping):
                        track_errors[track].append(
                            f"{block_prefix}:missing_realism:{dimension}"
                        )
                        continue
                    if not str(dimension_record.get("evidence", "")).strip():
                        track_errors[track].append(
                            f"{block_prefix}:missing_realism_evidence:{dimension}"
                        )
                    if not str(dimension_record.get("limitation", "")).strip():
                        track_errors[track].append(
                            f"{block_prefix}:missing_realism_limitation:{dimension}"
                        )
                block_cases = block.get("case_ids")
                if not isinstance(block_cases, list) or not block_cases:
                    track_errors[track].append(f"{block_prefix}:invalid_case_ids")
                    continue
                for raw_case_id in block_cases:
                    case_id = str(raw_case_id).strip()
                    if not case_id:
                        track_errors[track].append(f"{block_prefix}:invalid_case_id")
                        continue
                    if case_id in case_ids[track]:
                        track_errors[track].append(f"{block_prefix}:duplicate_case:{case_id}")
                    case_ids[track].add(case_id)
                    if case_id in development_case_ids:
                        track_errors[track].append(f"development_case_overlap:{case_id}")
                    observed = result_index.get((track, case_id))
                    if observed is None:
                        track_errors[track].append(f"missing_completed_case:{track}:{case_id}")
                        continue
                    if setting_id not in observed["settings"]:
                        track_errors[track].append(
                            f"setting_mismatch:{track}:{case_id}:expected={setting_id}"
                        )
                    for method_id in _target_field(target, "method_ids"):
                        if str(method_id) not in observed["methods"]:
                            track_errors[track].append(
                                f"missing_headline_result:{case_id}:{method_id}"
                            )

                if len(track_errors[track]) == error_count_before_block:
                    observable = block["economic_observable"]
                    semantic = str(observable["semantic"])
                    semantic_counts[track][semantic] += 1
                    for claim in observable["claims_supported"]:
                        claim_support_counts[str(claim)] += 1
                    source_uris[track].add(str(block["source_uri"]))
                    license_id = str(block["license_id"])
                    license_counts[license_id] = license_counts.get(license_id, 0) + 1

            representativeness = item.get("representativeness")
            if not isinstance(representativeness, Mapping):
                track_errors[track].append(f"{prefix}:missing_representativeness")
            else:
                metrics = representativeness.get("metrics")
                if not isinstance(metrics, list) or not metrics:
                    track_errors[track].append(f"{prefix}:missing_representativeness_metrics")
                if not isinstance(representativeness.get("coverage"), (int, float)):
                    track_errors[track].append(f"{prefix}:missing_representativeness_coverage")
                if not str(representativeness.get("limitations", "")).strip():
                    track_errors[track].append(f"{prefix}:missing_representativeness_limitations")

            contrasts = item.get("contrasts")
            if not isinstance(contrasts, list) or not contrasts:
                track_errors[track].append(f"{prefix}:missing_contrasts")
            else:
                for contrast_index, raw_contrast in enumerate(contrasts):
                    contrast_prefix = f"{prefix}:contrast_{contrast_index}"
                    if not isinstance(raw_contrast, Mapping):
                        track_errors[track].append(f"{contrast_prefix}:not_object")
                        continue
                    contrast = {str(key): value for key, value in raw_contrast.items()}
                    required = (
                        "contrast_id", "metric", "estimand", "ci_method",
                        "multiplicity_family", "worst_block",
                    )
                    for field in required:
                        if not str(contrast.get(field, "")).strip():
                            track_errors[track].append(f"{contrast_prefix}:missing_{field}")
                    if contrast.get("inference_unit") != "independent_block":
                        track_errors[track].append(f"{contrast_prefix}:invalid_inference_unit")
                    if contrast.get("decision") not in _DECISIONS:
                        track_errors[track].append(f"{contrast_prefix}:invalid_decision")
                    for field in ("effect", "ci_low", "ci_high"):
                        if not isinstance(contrast.get(field), (int, float)):
                            track_errors[track].append(f"{contrast_prefix}:missing_{field}")

    if global_invalid:
        return HeldoutEvidenceAudit(
            (),
            {track: 0 for track in HELDOUT_TRACKS},
            semantic_counts,
            claim_support_counts,
            {track: 0 for track in HELDOUT_TRACKS},
            {},
            tuple(errors),
        )

    for track in HELDOUT_TRACKS:
        if len(block_ids[track]) < minimum_blocks_per_track:
            track_errors[track].append(
                f"insufficient_blocks:{track}:{len(block_ids[track])}<{minimum_blocks_per_track}"
            )
        errors.extend(track_errors[track])
    covered = tuple(sorted(
        track for track in HELDOUT_TRACKS if not track_errors[track]
    ))
    counts = {
        track: len(block_ids[track]) if not track_errors[track] else 0
        for track in HELDOUT_TRACKS
    }
    return HeldoutEvidenceAudit(
        covered,
        counts,
        semantic_counts,
        claim_support_counts,
        {track: len(source_uris[track]) for track in HELDOUT_TRACKS},
        dict(sorted(license_counts.items())),
        tuple(errors),
    )


__all__ = [
    "ECONOMIC_OBSERVABLE_SEMANTICS",
    "economic_observable_errors",
    "HELDOUT_TRACKS",
    "REALISM_DIMENSIONS",
    "ECONOMIC_OBSERVABLE_SEMANTICS",
    "HeldoutEvidenceAudit",
    "audit_heldout_manifests",
]
