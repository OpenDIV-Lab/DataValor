"""Validation of third-party open-development case contribution packages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from .heldout_evidence import economic_observable_errors
from .runner import build_cases

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRACKS = frozenset({"valuation", "procurement", "trading"})
_INDEPENDENCE_UNITS = frozenset(
    {"base_dataset", "generator_family", "market_source"}
)
_PRIVACY_CLASSES = frozenset({"no_personal_data", "deidentified"})
_REALISM_DIMENSIONS = ("data", "utility", "participant_type", "institutional")


@dataclass(frozen=True)
class CaseSubmissionValidation:
    valid: bool
    review_eligible: bool
    evidence_scope: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    track: str
    setting_id: str
    case_count: int
    independence_unit_count: int
    package_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda value: value.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _mapping(raw: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        errors.append(f"{label} must be a mapping")
        return {}
    return {str(key): value for key, value in raw.items()}


def _required_string(
    raw: Mapping[str, Any], field: str, label: str, errors: list[str]
) -> str:
    value = str(raw.get(field, "")).strip()
    if not value:
        errors.append(f"missing required field: {label}.{field}")
    return value


def _http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _bound_file(
    package: Path,
    raw_path: Any,
    expected_hash: Any,
    label: str,
    errors: list[str],
) -> Path | None:
    value = str(raw_path or "").strip()
    relative = Path(value)
    if (
        not value
        or relative.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        errors.append(f"{label} must stay inside the case package")
        return None
    candidate = package / relative
    try:
        candidate.resolve().relative_to(package.resolve())
    except ValueError:
        errors.append(f"{label} must stay inside the case package")
        return None
    if not candidate.is_file() or candidate.is_symlink():
        errors.append(f"{label} is not a regular file")
        return None
    expected = str(expected_hash or "").strip()
    if not _SHA256.fullmatch(expected) or _sha256(candidate) != expected:
        hash_label = label.rsplit(".", 1)[0] + "." + label.rsplit(".", 1)[1]
        errors.append(f"{hash_label.replace('_path', '_sha256')} mismatch")
        return candidate
    return candidate


def _known_surface() -> tuple[dict[str, str], set[str]]:
    setting_tracks: dict[str, str] = {}
    case_ids: set[str] = set()
    for track, cases in build_cases().items():
        for case in cases:
            setting = str(case.metadata.get("benchmark_setting", ""))
            if setting:
                setting_tracks.setdefault(setting, track)
            case_ids.add(case.case_id)
    return setting_tracks, case_ids


def validate_case_submission(path: str | Path) -> CaseSubmissionValidation:
    """Validate a case pack without executing contributor-supplied code."""

    package = Path(path)
    manifest_path = package / "case_submission.yaml"
    errors: list[str] = []
    warnings: list[str] = []
    payload: dict[str, Any] = {}
    if not manifest_path.is_file():
        errors.append("missing case_submission.yaml")
    else:
        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            payload = _mapping(loaded, "case submission", errors)
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"invalid case_submission.yaml: {exc.__class__.__name__}")

    if payload.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if payload.get("submission_kind") != "open_case_admission":
        errors.append("submission_kind must be open_case_admission")
    for field in ("contributor", "case_pack_id"):
        if not str(payload.get(field, "")).strip():
            errors.append(f"missing required field: {field}")
    example_only = payload.get("example_only")
    if not isinstance(example_only, bool):
        errors.append("example_only must be boolean")
        example_only = True

    track = str(payload.get("track", "")).strip()
    if track not in _TRACKS:
        errors.append("track must be valuation, procurement, or trading")
    if payload.get("cohort") != "open_development":
        errors.append("cohort must be open_development")
    setting_id = str(payload.get("setting_id", "")).strip()
    setting_tracks, canonical_case_ids = _known_surface()
    if setting_id not in setting_tracks:
        errors.append(f"setting_id is not a canonical benchmark setting: {setting_id}")
    elif track in _TRACKS and setting_tracks[setting_id] != track:
        errors.append("setting_id does not belong to the declared track")

    bound_paths = [manifest_path]
    source = _mapping(payload.get("source"), "source", errors)
    for field in ("source_uri", "source_version", "license_id", "license_url"):
        _required_string(source, field, "source", errors)
    if not _http_url(str(source.get("source_uri", ""))):
        errors.append("source.source_uri must use http or https")
    if not _http_url(str(source.get("license_url", ""))):
        errors.append("source.license_url must use http or https")
    if source.get("redistributable") is not True:
        errors.append("source.redistributable must be true")
    source_path = _bound_file(
        package,
        source.get("input_path"),
        source.get("input_sha256"),
        "source.input_path",
        errors,
    )
    if source_path is not None:
        bound_paths.append(source_path)

    privacy = _mapping(payload.get("privacy"), "privacy", errors)
    privacy_class = str(privacy.get("classification", "")).strip()
    if privacy_class not in _PRIVACY_CLASSES:
        errors.append(
            "privacy.classification must be no_personal_data or deidentified"
        )
    _required_string(privacy, "review", "privacy", errors)

    independence = _mapping(payload.get("independence"), "independence", errors)
    independence_unit = str(independence.get("unit", "")).strip()
    if independence_unit not in _INDEPENDENCE_UNITS:
        errors.append(
            "independence.unit must be base_dataset, generator_family, or market_source"
        )
    raw_unit_ids = independence.get("unit_ids")
    unit_ids = (
        tuple(str(value).strip() for value in raw_unit_ids)
        if isinstance(raw_unit_ids, list)
        else ()
    )
    if not unit_ids or "" in unit_ids or len(set(unit_ids)) != len(unit_ids):
        errors.append("independence.unit_ids must contain unique non-empty values")

    realism = _mapping(payload.get("realism"), "realism", errors)
    for dimension in _REALISM_DIMENSIONS:
        _required_string(realism, dimension, "realism", errors)
    errors.extend(economic_observable_errors(payload.get("economic_observable")))

    transformation = _mapping(payload.get("transformation"), "transformation", errors)
    _required_string(transformation, "description", "transformation", errors)
    if transformation.get("deterministic") is not True:
        errors.append("transformation.deterministic must be true")
    transform_path = _bound_file(
        package,
        transformation.get("code_path"),
        transformation.get("code_sha256"),
        "transformation.code_path",
        errors,
    )
    if transform_path is not None:
        bound_paths.append(transform_path)

    raw_cases = payload.get("cases")
    cases = raw_cases if isinstance(raw_cases, list) else []
    if not cases:
        errors.append("cases must be a non-empty list")
    seen_case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _mapping(raw_case, f"cases[{index}]", errors)
        case_id = str(case.get("case_id", "")).strip()
        source_unit_id = str(case.get("source_unit_id", "")).strip()
        if not case_id:
            errors.append(f"cases[{index}].case_id must be non-empty")
        elif case_id in seen_case_ids:
            errors.append(f"duplicate case_id: {case_id}")
        elif case_id in canonical_case_ids:
            errors.append(
                f"case_id collides with a canonical benchmark case: {case_id}"
            )
        seen_case_ids.add(case_id)
        if source_unit_id not in unit_ids:
            errors.append(
                f"cases[{index}].source_unit_id is not declared in independence.unit_ids"
            )

    valid = not errors
    return CaseSubmissionValidation(
        valid=valid,
        review_eligible=valid and not example_only,
        evidence_scope="open_development_only",
        errors=tuple(errors),
        warnings=tuple(warnings),
        track=track,
        setting_id=setting_id,
        case_count=len({value for value in seen_case_ids if value}),
        independence_unit_count=len(set(unit_ids)),
        package_digest=_digest(bound_paths),
    )


__all__ = ["CaseSubmissionValidation", "validate_case_submission"]
