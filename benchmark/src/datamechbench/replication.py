"""Fail-closed contracts for a source-disjoint held-out replication wave."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

TRACKS = ("valuation", "procurement", "trading")
_MD5 = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReplicationProtocolAudit:
    replication_wave: str
    block_counts: Mapping[str, int]
    headline_method_count: int
    contrast_ids: tuple[str, ...]
    random_seeds: tuple[int, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ReplicationComparison:
    contrast_id: str
    track: str
    v1_effect: float | None
    v1_ci_low: float | None
    v1_ci_high: float | None
    v1_decision: str
    v1_blocks: int
    v2_effect: float | None
    v2_ci_low: float | None
    v2_ci_high: float | None
    v2_decision: str
    v2_blocks: int
    direction_category: str
    interval_relation: str
    replication_verdict: str


@dataclass(frozen=True)
class ReplicationBlockEffect:
    wave: str
    contrast_id: str
    track: str
    block_id: str
    effect: float


@dataclass(frozen=True)
class ReplicationReport:
    comparisons: tuple[ReplicationComparison, ...]
    block_effects: tuple[ReplicationBlockEffect, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_yaml(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        errors.append(f"invalid_{label}")
        return {}
    if not isinstance(payload, Mapping):
        errors.append(f"invalid_{label}")
        return {}
    return dict(payload)


def _load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"invalid_{label}")
        return {}
    if not isinstance(payload, Mapping):
        errors.append(f"invalid_{label}")
        return {}
    return dict(payload)


def _repository_file(raw: Any, root: Path, label: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, Mapping):
        errors.append(f"missing_{label}")
        return None
    relative = str(raw.get("path", "")).strip()
    expected = str(raw.get("sha256", "")).strip()
    candidate = Path(relative)
    if not relative or candidate.is_absolute():
        errors.append(f"unsafe_{label}_path")
        return None
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root.resolve())
    except ValueError:
        errors.append(f"unsafe_{label}_path")
        return None
    if not resolved.is_file():
        errors.append(f"missing_{label}")
        return None
    if not _SHA256.fullmatch(expected):
        errors.append(f"invalid_{label}_sha256")
        return None
    observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if observed != expected:
        errors.append(f"{label}_sha256_mismatch")
        return None
    return resolved


def _dated_trading_sources(sources: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = sources.get("trading", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping) and "date" in item]


def _block_ids(sources: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    output: dict[str, tuple[str, ...]] = {}
    for track in ("valuation", "procurement"):
        rows = sources.get(track, [])
        output[track] = tuple(
            str(item.get("block_id", "")).strip()
            for item in rows
            if isinstance(item, Mapping)
        ) if isinstance(rows, list) else ()
    output["trading"] = tuple(
        str(item.get("block_id", "")).strip()
        for item in _dated_trading_sources(sources)
    )
    return output


def _source_identities(sources: Mapping[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    valuation = sources.get("valuation", [])
    procurement = sources.get("procurement", [])
    return {
        "valuation": tuple(
            ("openml_id", str(item.get("openml_id", "")))
            for item in valuation
            if isinstance(item, Mapping)
        ) if isinstance(valuation, list) else (),
        "procurement": tuple(
            ("cohort_date", str(item.get("cohort_date", "")))
            for item in procurement
            if isinstance(item, Mapping)
        ) if isinstance(procurement, list) else (),
        "trading": tuple(
            ("date", str(item.get("date", "")))
            for item in _dated_trading_sources(sources)
        ),
    }


def audit_replication_protocol(
    config_path: Path,
    protocol_path: Path,
    v1_manifest_path: Path,
    repository_root: Path,
) -> ReplicationProtocolAudit:
    """Audit frozen choices without reading any replication outcomes."""

    errors: list[str] = []
    root = Path(repository_root).resolve()
    config = _load_yaml(Path(config_path), "config", errors)
    protocol = _load_json(Path(protocol_path), "protocol", errors)
    v1_manifest = _load_json(Path(v1_manifest_path), "v1_manifest", errors)

    protocol_payload = dict(protocol)
    stored_hash = str(protocol_payload.pop("protocol_hash", ""))
    if not _SHA256.fullmatch(stored_hash) or stored_hash != _canonical_hash(protocol_payload):
        errors.append("invalid_protocol_hash")
    if protocol.get("manifest_kind") != "confirmatory_protocol":
        errors.append("invalid_protocol_kind")
    if protocol.get("confirmatory_outcomes") is not None:
        errors.append("protocol_contains_outcomes")

    v1_protocol_path = _repository_file(
        v1_manifest.get("protocol"), root, "v1_protocol", errors
    )
    v1_protocol = (
        _load_json(v1_protocol_path, "v1_protocol", errors)
        if v1_protocol_path is not None
        else {}
    )

    for field in (
        "sources",
        "transformations",
        "contrasts",
        "headline_methods",
        "development_artifact_hashes",
    ):
        if config.get(field) != protocol.get(field):
            errors.append(f"config_protocol_mismatch:{field}")

    wave = str(config.get("replication_wave", ""))
    if wave != "v2":
        errors.append("invalid_replication_wave")
    if config.get("cohort") != "heldout":
        errors.append("invalid_cohort")
    if config.get("minimum_blocks_per_track") != 2:
        errors.append("invalid_minimum_blocks")

    sources = config.get("sources")
    if not isinstance(sources, Mapping):
        sources = {}
        errors.append("invalid_sources")
    v1_sources = v1_protocol.get("sources")
    if not isinstance(v1_sources, Mapping):
        v1_sources = {}
        errors.append("invalid_v1_sources")

    blocks = _block_ids(sources)
    block_counts = {track: len(blocks[track]) for track in TRACKS}
    for track in TRACKS:
        if len(blocks[track]) != 2 or any(not value for value in blocks[track]):
            errors.append(f"invalid_block_count:{track}:{len(blocks[track])}")
        if len(set(blocks[track])) != len(blocks[track]):
            errors.append(f"duplicate_block_id:{track}")

    v1_blocks: dict[str, set[str]] = {track: set() for track in TRACKS}
    tracks = v1_manifest.get("tracks", {})
    if isinstance(tracks, Mapping):
        for track in TRACKS:
            record = tracks.get(track, {})
            rows = record.get("blocks", []) if isinstance(record, Mapping) else []
            if isinstance(rows, list):
                v1_blocks[track] = {
                    str(item.get("block_id", ""))
                    for item in rows
                    if isinstance(item, Mapping)
                }
    for track in TRACKS:
        for block in blocks[track]:
            if block in v1_blocks[track]:
                errors.append(f"v1_block_overlap:{track}:{block}")

    v1_identities = {
        track: set(values)
        for track, values in _source_identities(v1_sources).items()
    }
    for track, identities in _source_identities(sources).items():
        for field, value in identities:
            if not value:
                errors.append(f"missing_source_identity:{track}:{field}")
            if (field, value) in v1_identities[track]:
                errors.append(f"v1_source_overlap:{track}:{field}:{value}")

    valuation_sources = sources.get("valuation", [])
    if isinstance(valuation_sources, list):
        for source in valuation_sources:
            if not isinstance(source, Mapping):
                errors.append("invalid_source:valuation")
                continue
            raw_filename = str(source.get("raw_filename", ""))
            raw_path = Path(raw_filename)
            if (
                not raw_filename
                or raw_path.is_absolute()
                or len(raw_path.parts) != 1
                or raw_path.name != raw_filename
            ):
                errors.append(f"unsafe_source_path:valuation:{raw_filename}")
            if not _MD5.fullmatch(str(source.get("expected_md5", ""))):
                errors.append(f"invalid_source_md5:valuation:{source.get('source_id', '')}")
            for field in ("canonical_source", "data_url", "license_id", "target_attribute"):
                if not str(source.get(field, "")).strip():
                    errors.append(f"missing_source_field:valuation:{field}")

    config_contrasts = config.get("contrasts", [])
    v1_contrasts = v1_protocol.get("contrasts", [])
    if config_contrasts != v1_contrasts:
        errors.append("v1_contrast_mismatch")
    config_methods = config.get("headline_methods", {})
    v1_methods = v1_protocol.get("headline_methods", {})
    if config_methods != v1_methods:
        errors.append("v1_headline_method_mismatch")

    transformations = config.get("transformations", {})
    execution = (
        transformations.get("execution_contract", {})
        if isinstance(transformations, Mapping)
        else {}
    )
    raw_seeds = config.get("random_seeds", [])
    random_seeds = tuple(int(seed) for seed in raw_seeds) if isinstance(raw_seeds, list) else ()
    if (
        list(random_seeds) != [1701, 2903, 4703]
        or execution.get("random_seeds") != list(random_seeds)
        or execution.get("replication_wave") != "v2"
        or execution.get("stopping_rule") != config.get("stopping_rule")
        or execution.get("result_contract") != config.get("result_contract")
    ):
        errors.append("seed_panel_not_frozen")

    methods = config_methods if isinstance(config_methods, Mapping) else {}
    method_count = sum(
        len(value) for value in methods.values() if isinstance(value, list)
    )
    contrast_ids = tuple(
        str(item.get("contrast_id", ""))
        for item in config_contrasts
        if isinstance(item, Mapping)
    ) if isinstance(config_contrasts, list) else ()

    return ReplicationProtocolAudit(
        replication_wave=wave,
        block_counts=block_counts,
        headline_method_count=method_count,
        contrast_ids=contrast_ids,
        random_seeds=random_seeds,
        errors=tuple(dict.fromkeys(errors)),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _direction_category(v1: float | None, v2: float | None) -> str:
    if v1 is None or v2 is None:
        return "not_auditable"
    tolerance = 1e-12
    v1_zero = abs(v1) <= tolerance
    v2_zero = abs(v2) <= tolerance
    if v1_zero and v2_zero:
        return "both_zero"
    if v1_zero:
        return "emergent_nonzero"
    if v2_zero:
        return "attenuated_to_zero"
    if (v1 > 0) == (v2 > 0):
        return "same_sign"
    return "sign_disagreement"


def _interval_relation(
    v1_low: float | None,
    v1_high: float | None,
    v2_low: float | None,
    v2_high: float | None,
) -> str:
    if None in (v1_low, v1_high, v2_low, v2_high):
        return "not_auditable"
    assert v1_low is not None and v1_high is not None
    assert v2_low is not None and v2_high is not None
    return "overlap" if max(v1_low, v2_low) <= min(v1_high, v2_high) else "disjoint"


def _replication_verdict(direction: str, *, auditable: bool) -> str:
    if not auditable or direction == "not_auditable":
        return "not_auditable"
    return {
        "same_sign": "directionally_consistent",
        "both_zero": "boundary_reproduced",
        "sign_disagreement": "heterogeneous",
        "emergent_nonzero": "magnitude_shift",
        "attenuated_to_zero": "magnitude_shift",
    }[direction]


def analyze_replication_wave(
    v1_contrasts: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    v2_contrasts: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    minimum_v2_blocks: int = 2,
) -> ReplicationReport:
    """Compare waves descriptively without pooling their inference."""

    errors: list[str] = []
    v1_index = {str(row.get("contrast_id", "")): row for row in v1_contrasts}
    v2_index = {str(row.get("contrast_id", "")): row for row in v2_contrasts}
    if len(v1_index) != len(v1_contrasts):
        errors.append("duplicate_v1_contrast_id")
    if len(v2_index) != len(v2_contrasts):
        errors.append("duplicate_v2_contrast_id")
    if set(v1_index) != set(v2_index):
        missing = sorted(set(v1_index) - set(v2_index))
        extra = sorted(set(v2_index) - set(v1_index))
        errors.append(f"contrast_set_mismatch:missing={missing}:extra={extra}")

    comparisons: list[ReplicationComparison] = []
    block_rows: list[ReplicationBlockEffect] = []
    for contrast_id, v1 in v1_index.items():
        v2 = v2_index.get(contrast_id, {})
        track = str(v1.get("track", v2.get("track", "")))
        v1_blocks_raw = v1.get("block_effects", {})
        v2_blocks_raw = v2.get("block_effects", {})
        v1_blocks = v1_blocks_raw if isinstance(v1_blocks_raw, Mapping) else {}
        v2_blocks = v2_blocks_raw if isinstance(v2_blocks_raw, Mapping) else {}
        enough_blocks = len(v2_blocks) >= minimum_v2_blocks
        if not enough_blocks:
            errors.append(
                f"insufficient_v2_blocks:{contrast_id}:{len(v2_blocks)}<{minimum_v2_blocks}"
            )
        for wave, values in (("v1", v1_blocks), ("v2", v2_blocks)):
            for block_id, raw_effect in values.items():
                effect = _optional_float(raw_effect)
                if effect is None:
                    errors.append(f"invalid_block_effect:{wave}:{contrast_id}:{block_id}")
                    continue
                block_rows.append(
                    ReplicationBlockEffect(
                        wave=wave,
                        contrast_id=contrast_id,
                        track=track,
                        block_id=str(block_id),
                        effect=effect,
                    )
                )
        v1_effect = _optional_float(v1.get("effect"))
        v2_effect = _optional_float(v2.get("effect"))
        v1_low = _optional_float(v1.get("ci_low"))
        v1_high = _optional_float(v1.get("ci_high"))
        v2_low = _optional_float(v2.get("ci_low"))
        v2_high = _optional_float(v2.get("ci_high"))
        direction = _direction_category(v1_effect, v2_effect)
        comparisons.append(
            ReplicationComparison(
                contrast_id=contrast_id,
                track=track,
                v1_effect=v1_effect,
                v1_ci_low=v1_low,
                v1_ci_high=v1_high,
                v1_decision=str(v1.get("decision", "")),
                v1_blocks=len(v1_blocks),
                v2_effect=v2_effect,
                v2_ci_low=v2_low,
                v2_ci_high=v2_high,
                v2_decision=str(v2.get("decision", "")),
                v2_blocks=len(v2_blocks),
                direction_category=direction,
                interval_relation=_interval_relation(
                    v1_low, v1_high, v2_low, v2_high
                ),
                replication_verdict=_replication_verdict(
                    direction,
                    auditable=enough_blocks and v2_effect is not None,
                ),
            )
        )
    return ReplicationReport(
        comparisons=tuple(comparisons),
        block_effects=tuple(block_rows),
        errors=tuple(dict.fromkeys(errors)),
    )


__all__ = [
    "ReplicationBlockEffect",
    "ReplicationComparison",
    "ReplicationProtocolAudit",
    "ReplicationReport",
    "analyze_replication_wave",
    "audit_replication_protocol",
]
