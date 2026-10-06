"""Pinned direct data-market listing-price calibration profiles."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import numpy as np

FORBIDDEN_IDENTITY_FIELDS = frozenset({
    "coverage",
    "data_sample",
    "description",
    "provider",
    "title",
    "url",
})
REQUIRED_COLUMNS = frozenset({"platform", "price", "price_mode"})
RECEIPT_NAME = "dadada_source_receipt.json"
PROFILES_NAME = "dadada_price_profiles.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _parse_price(raw: Any, row_number: int) -> float:
    try:
        value = float(Decimal(str(raw).strip()))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid price at CSV row {row_number}: {raw!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid price at CSV row {row_number}: {raw!r}")
    return value


def _statistics(values: np.ndarray) -> dict[str, float]:
    return {
        "minimum": float(np.min(values)),
        "q25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "q75": float(np.quantile(values, 0.75)),
        "maximum": float(np.max(values)),
    }


def _reported_costs(
    values: tuple[float, ...],
    *,
    seller_count: int,
    winsor_quantiles: tuple[float, float],
) -> tuple[dict[str, str], dict[str, float]]:
    array = np.asarray(values, dtype=float)
    low, high = winsor_quantiles
    low_value, high_value = np.quantile(array, (low, high))
    winsorized = np.clip(array, low_value, high_value)
    transformed = np.log1p(winsorized)
    quantiles = (np.arange(seller_count, dtype=float) + 0.5) / seller_count
    selected = np.quantile(transformed, quantiles)
    median = float(np.median(selected))
    if not math.isfinite(median) or median <= 0:
        raise ValueError("selected listing-price median must be positive and finite")
    normalized = selected / median
    costs = {
        f"o{index}": str(Decimal(str(round(float(value), 9))))
        for index, value in enumerate(normalized)
    }
    diagnostics = {
        "winsor_lower_price": float(low_value),
        "winsor_upper_price": float(high_value),
        "selected_log_median": median,
    }
    return costs, diagnostics


def build_dadada_profiles(
    path: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the pinned table and retain anonymous cohort distributions only."""

    source = _require_mapping(protocol.get("source"), "source")
    transformation = _require_mapping(
        protocol.get("transformation"), "transformation"
    )
    raw_sha256 = _sha256(path)
    if raw_sha256 != source.get("expected_sha256"):
        raise ValueError(
            "source SHA-256 mismatch: "
            f"expected={source.get('expected_sha256')} observed={raw_sha256}"
        )

    explicit_modes = tuple(str(item) for item in transformation["explicit_price_modes"])
    grouped: dict[tuple[str, str], list[float]] = {}
    row_count = 0
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("DaDaDa CSV is missing required columns")
        for row_number, row in enumerate(reader, start=2):
            row_count += 1
            value = _parse_price(row.get("price"), row_number)
            mode = str(row.get("price_mode", "")).strip()
            platform = str(row.get("platform", "")).strip()
            if not platform or not mode:
                raise ValueError(f"empty platform or price_mode at CSV row {row_number}")
            if value > 0 and mode not in explicit_modes:
                raise ValueError(
                    f"positive price outside explicit modes at CSV row {row_number}: {mode}"
                )
            if value > 0:
                grouped.setdefault((platform, mode), []).append(value)

    expected_rows = int(source["expected_row_count"])
    if row_count != expected_rows:
        raise ValueError(
            f"source row count mismatch: expected={expected_rows} observed={row_count}"
        )

    minimum = int(transformation["minimum_cohort_size"])
    seller_count = int(transformation["seller_count"])
    raw_winsor = tuple(float(item) for item in transformation["winsor_quantiles"])
    if len(raw_winsor) != 2 or not 0 <= raw_winsor[0] <= raw_winsor[1] <= 1:
        raise ValueError("winsor_quantiles must be an ordered pair in [0, 1]")
    winsor_quantiles = (raw_winsor[0], raw_winsor[1])

    expected_cohorts = protocol.get("cohorts")
    if not isinstance(expected_cohorts, list) or not expected_cohorts:
        raise ValueError("cohorts must be a non-empty list")
    cohort_rows: list[dict[str, Any]] = []
    for index, raw_cohort in enumerate(expected_cohorts):
        cohort = _require_mapping(raw_cohort, f"cohorts[{index}]")
        platform = str(cohort["platform"])
        mode = str(cohort["price_mode"])
        values = tuple(grouped.get((platform, mode), ()))
        if len(values) < minimum:
            raise ValueError(
                f"cohort {cohort['cohort_id']} below minimum cohort size: "
                f"{len(values)} < {minimum}"
            )
        expected_count = int(cohort["expected_row_count"])
        if len(values) != expected_count:
            raise ValueError(
                f"cohort row count mismatch:{cohort['cohort_id']}:"
                f"expected={expected_count}:observed={len(values)}"
            )
        costs, diagnostics = _reported_costs(
            values,
            seller_count=seller_count,
            winsor_quantiles=winsor_quantiles,
        )
        cohort_rows.append({
            "cohort_id": str(cohort["cohort_id"]),
            "platform": platform,
            "price_mode": mode,
            "source_row_count": len(values),
            "raw_price_statistics": _statistics(np.asarray(values, dtype=float)),
            "transformation_diagnostics": diagnostics,
            "reported_costs": costs,
        })

    eligible = {
        (platform, mode)
        for (platform, mode), values in grouped.items()
        if len(values) >= minimum
    }
    declared = {
        (str(item["platform"]), str(item["price_mode"]))
        for item in expected_cohorts
    }
    if eligible != declared:
        raise ValueError(
            "eligible cohort set mismatch: "
            f"undeclared={sorted(eligible - declared)} missing={sorted(declared - eligible)}"
        )

    return {
        "schema_version": "1.0",
        "artifact_kind": "anonymous_direct_data_market_price_profiles",
        "study_id": str(protocol["study_id"]),
        "source": {
            "repository": source["repository"],
            "commit": source["commit"],
            "data_path": source["data_path"],
            "data_sha256": raw_sha256,
            "license_id": source["license_id"],
            "license_url": source["license_url"],
            "license_sha256": source["license_sha256"],
        },
        "source_row_count": row_count,
        "eligible_explicit_price_row_count": sum(len(values) for values in grouped.values()),
        "transformation": {
            "explicit_price_modes": list(explicit_modes),
            "minimum_cohort_size": minimum,
            "seller_count": seller_count,
            "winsor_quantiles": list(winsor_quantiles),
            "price_transform": transformation["price_transform"],
            "identity_policy": transformation["identity_policy"],
        },
        "claim_boundaries": dict(protocol["claim_boundaries"]),
        "cohorts": sorted(cohort_rows, key=lambda item: item["cohort_id"]),
    }


def _forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in FORBIDDEN_IDENTITY_FIELDS:
                found.add(str(key))
            found.update(_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys(item))
    return found


def audit_dadada_profiles(
    payload: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[str, ...]:
    """Fail closed on profile drift, identity leakage, or invalid asks."""

    errors: list[str] = []
    source = _require_mapping(protocol.get("source"), "source")
    transformation = _require_mapping(
        protocol.get("transformation"), "transformation"
    )
    if payload.get("source_row_count") != source.get("expected_row_count"):
        errors.append("source_row_count_mismatch")
    observed_source = payload.get("source")
    if not isinstance(observed_source, Mapping) or (
        observed_source.get("data_sha256") != source.get("expected_sha256")
    ):
        errors.append("source_sha256_mismatch")
    for field in sorted(_forbidden_keys(payload)):
        errors.append(f"forbidden_identity_field:{field}")

    cohorts = payload.get("cohorts")
    if not isinstance(cohorts, list):
        return tuple((*errors, "cohorts_not_list"))
    ids: set[str] = set()
    expected = {
        str(item["cohort_id"]): item for item in protocol.get("cohorts", [])
    }
    for item in cohorts:
        if not isinstance(item, Mapping):
            errors.append("cohort_not_mapping")
            continue
        cohort_id = str(item.get("cohort_id", ""))
        if cohort_id in ids:
            errors.append(f"duplicate_cohort_id:{cohort_id}")
        ids.add(cohort_id)
        frozen = expected.get(cohort_id)
        if frozen is None:
            errors.append(f"unexpected_cohort:{cohort_id}")
            continue
        for field in ("platform", "price_mode"):
            if item.get(field) != frozen.get(field):
                errors.append(f"cohort_{field}_mismatch:{cohort_id}")
        if item.get("source_row_count") != frozen.get("expected_row_count"):
            errors.append(f"cohort_row_count_mismatch:{cohort_id}")
        costs = item.get("reported_costs")
        seller_count = int(transformation["seller_count"])
        if not isinstance(costs, Mapping) or set(costs) != {
            f"o{index}" for index in range(seller_count)
        }:
            errors.append(f"invalid_reported_cost_keys:{cohort_id}")
            continue
        values: list[Decimal] = []
        for raw in costs.values():
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                value = Decimal("NaN")
            values.append(value)
        if any(not value.is_finite() or value <= 0 for value in values):
            errors.append(f"invalid_reported_cost:{cohort_id}")
        elif values != sorted(values):
            errors.append(f"unsorted_reported_costs:{cohort_id}")
    for missing in sorted(set(expected) - ids):
        errors.append(f"missing_cohort:{missing}")
    if payload.get("claim_boundaries") != protocol.get("claim_boundaries"):
        errors.append("claim_boundaries_mismatch")
    return tuple(sorted(set(errors)))


def build_calibration_artifacts(
    raw_path: Path,
    output_dir: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic source receipt and anonymized price profiles."""

    payload = build_dadada_profiles(raw_path, protocol)
    source = _require_mapping(protocol.get("source"), "source")
    receipt = {
        "schema_version": "1.0",
        "artifact_kind": "external_source_receipt",
        "study_id": protocol["study_id"],
        "repository": source["repository"],
        "commit": source["commit"],
        "commit_date": source["commit_date"],
        "data_path": source["data_path"],
        "data_url": source["data_url"],
        "data_sha256": source["expected_sha256"],
        "data_bytes": raw_path.stat().st_size,
        "data_row_count": source["expected_row_count"],
        "license_id": source["license_id"],
        "license_url": source["license_url"],
        "license_sha256": source["license_sha256"],
        "redistribution_policy": "raw_csv_rebuild_input_not_release_member",
    }
    receipt_path = output_dir / RECEIPT_NAME
    _atomic_write(receipt_path, _canonical_json(receipt))
    payload["source_receipt"] = {
        "path": RECEIPT_NAME,
        "sha256": _sha256(receipt_path),
    }
    profiles_path = output_dir / PROFILES_NAME
    _atomic_write(profiles_path, _canonical_json(payload))
    verified = verify_calibration_artifacts(output_dir, protocol)
    if not verified["valid"]:
        raise ValueError(f"built calibration artifacts failed verification: {verified['errors']}")
    return {
        "source_row_count": payload["source_row_count"],
        "eligible_explicit_price_row_count": payload[
            "eligible_explicit_price_row_count"
        ],
        "cohort_count": len(payload["cohorts"]),
        "receipt_sha256": _sha256(receipt_path),
        "profiles_sha256": _sha256(profiles_path),
    }


def verify_calibration_artifacts(
    output_dir: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify derived artifacts without requiring the external raw table."""

    errors: list[str] = []
    receipt_path = output_dir / RECEIPT_NAME
    profiles_path = output_dir / PROFILES_NAME
    if not receipt_path.is_file():
        errors.append(f"missing:{RECEIPT_NAME}")
    if not profiles_path.is_file():
        errors.append(f"missing:{PROFILES_NAME}")
    if errors:
        return {"valid": False, "errors": errors}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_json:{type(exc).__name__}"]}
    errors.extend(audit_dadada_profiles(payload, protocol))
    source = _require_mapping(protocol.get("source"), "source")
    expected_receipt = {
        "repository": source["repository"],
        "commit": source["commit"],
        "data_path": source["data_path"],
        "data_url": source["data_url"],
        "data_sha256": source["expected_sha256"],
        "data_row_count": source["expected_row_count"],
        "license_id": source["license_id"],
        "license_url": source["license_url"],
        "license_sha256": source["license_sha256"],
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            errors.append(f"receipt_{key}_mismatch")
    binding = payload.get("source_receipt")
    if not isinstance(binding, Mapping):
        errors.append("missing_source_receipt_binding")
    else:
        if binding.get("path") != RECEIPT_NAME:
            errors.append("source_receipt_path_mismatch")
        if binding.get("sha256") != _sha256(receipt_path):
            errors.append("source_receipt_hash_mismatch")
    return {"valid": not errors, "errors": sorted(set(errors))}


__all__ = [
    "PROFILES_NAME",
    "RECEIPT_NAME",
    "audit_dadada_profiles",
    "build_calibration_artifacts",
    "build_dadada_profiles",
    "verify_calibration_artifacts",
]
