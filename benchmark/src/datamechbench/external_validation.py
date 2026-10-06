"""Fail-closed audit for comparisons against independently authored implementations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED_ORIGINS = frozenset({"official_upstream", "independent_reimplementation"})
_REQUIRED_ARTIFACT_ROLES = frozenset({
    "external_source",
    "external_license",
    "comparison_fixtures",
    "comparison_results",
    "validation_runner",
})
_DEPENDENCY_ROLE_PREFIX = "external_dependency_"


def _mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): value for key, value in raw.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(raw: Any, root: Path, label: str) -> Path:
    value = str(raw or "").strip()
    candidate = Path(value)
    if not value or candidate.is_absolute():
        raise ValueError(f"{label} must be a non-empty repository-relative path")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _float(raw: Any, label: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{label} must be finite")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _audit_boundary_comparisons(
    result: Mapping[str, Any],
    validation_id: str,
    tolerance: float,
    occupied_case_ids: set[str],
) -> list[str]:
    """Validate optional, explicitly non-agreeing semantic boundary fixtures."""

    errors: list[str] = []
    raw_boundaries = result.get("boundary_comparisons")
    declared_count = result.get("boundary_fixture_count")
    if raw_boundaries is None:
        if declared_count not in (None, 0):
            errors.append(f"boundary_count_mismatch:{validation_id}")
        return errors
    if not isinstance(raw_boundaries, list):
        return [f"invalid_boundary_comparisons:{validation_id}"]
    if (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count != len(raw_boundaries)
    ):
        errors.append(f"boundary_count_mismatch:{validation_id}")
    for index, raw_boundary in enumerate(raw_boundaries):
        try:
            boundary = _mapping(raw_boundary, f"boundary comparison {index}")
            case_id = str(boundary.get("case_id", "")).strip()
            if not case_id or case_id in occupied_case_ids:
                errors.append(
                    f"invalid_boundary_case_id:{validation_id}:{case_id or index}"
                )
                continue
            occupied_case_ids.add(case_id)
            if boundary.get("status") != "expected_semantic_boundary":
                errors.append(f"invalid_boundary_status:{validation_id}:{case_id}")
            if boundary.get("matches_declared_difference") is not True:
                errors.append(f"boundary_not_matched:{validation_id}:{case_id}")
            vector_names = (
                "local_scores",
                "external_scores",
                "expected_local_scores",
                "expected_external_scores",
            )
            vectors = {name: boundary.get(name) for name in vector_names}
            first = vectors[vector_names[0]]
            if (
                not isinstance(first, list)
                or not first
                or any(
                    not isinstance(vectors[name], list)
                    or len(vectors[name]) != len(first)
                    for name in vector_names[1:]
                )
            ):
                errors.append(f"invalid_boundary_vectors:{validation_id}:{case_id}")
                continue
            numeric = {
                name: [_float(value, f"boundary {name}") for value in values]
                for name, values in vectors.items()
                if isinstance(values, list)
            }
            local = numeric["local_scores"]
            external = numeric["external_scores"]
            expected_local = numeric["expected_local_scores"]
            expected_external = numeric["expected_external_scores"]
            if any(
                abs(observed - expected) > tolerance
                for observed, expected in zip(local, expected_local, strict=True)
            ) or any(
                abs(observed - expected) > tolerance
                for observed, expected in zip(
                    external, expected_external, strict=True
                )
            ):
                errors.append(
                    f"boundary_fixture_oracle_disagreement:{validation_id}:{case_id}"
                )
            observed_difference = max(
                abs(left - right)
                for left, right in zip(local, external, strict=True)
            )
            if observed_difference <= tolerance:
                errors.append(f"boundary_not_discrepant:{validation_id}:{case_id}")
            declared_difference = _float(
                boundary.get("maximum_absolute_difference"),
                "boundary maximum difference",
            )
            if not math.isclose(
                declared_difference,
                observed_difference,
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                errors.append(
                    f"boundary_difference_mismatch:{validation_id}:{case_id}"
                )
        except (ValueError, KeyError) as exc:
            errors.append(
                f"invalid_boundary_comparison:{validation_id}:{index}:{exc}"
            )
    return errors


def _audit_record(
    record_path: Path,
    repository_root: Path,
    expected_method_ids: set[str],
    minimum_fixtures: int,
) -> tuple[
    list[str],
    str | None,
    bool,
    int,
    float,
    str | None,
    str | None,
    str,
    str | None,
]:
    errors: list[str] = []
    method_id: str | None = None
    official = False
    fixture_count = 0
    maximum_error = 0.0
    source_url: str | None = None
    repository_url: str | None = None
    track: str | None = None
    validation_id = record_path.stem
    try:
        record = _mapping(
            json.loads(record_path.read_text(encoding="utf-8")),
            "external validation record",
        )
        validation_id = str(record.get("validation_id", "")).strip() or validation_id
        if record.get("schema_version") != "1.0":
            errors.append(f"unsupported_schema_version:{validation_id}")
        if record.get("record_kind") != "external_implementation_validation":
            errors.append(f"invalid_record_kind:{validation_id}")
        method_id = str(record.get("method_id", "")).strip()
        if method_id not in expected_method_ids:
            errors.append(f"non_headline_method:{validation_id}:{method_id or '<missing>'}")
        track = str(record.get("track", "")).strip() or None
        if track is None:
            errors.append(f"missing_track:{validation_id}")
        if not str(record.get("claim_boundary", "")).strip():
            errors.append(f"missing_claim_boundary:{validation_id}")

        external = _mapping(
            record.get("external_implementation"), "external implementation"
        )
        source_url = str(external.get("source_url", "")).strip() or None
        repository_url = str(external.get("repository_url", "")).strip() or None
        origin = str(external.get("origin", "")).strip()
        official = origin == "official_upstream"
        if origin not in _ALLOWED_ORIGINS:
            errors.append(f"invalid_external_origin:{validation_id}")
        commit = str(external.get("commit_sha", "")).strip()
        if not _COMMIT.fullmatch(commit):
            errors.append(f"invalid_external_commit:{validation_id}")
        for field in ("repository_url", "source_url"):
            if not re.fullmatch(r"https://[^\s]+", str(external.get(field, ""))):
                errors.append(f"invalid_{field}:{validation_id}")
        if not str(external.get("name", "")).strip():
            errors.append(f"missing_external_name:{validation_id}")
        if not str(external.get("license_id", "")).strip():
            errors.append(f"missing_external_license:{validation_id}")

        raw_artifacts = record.get("artifacts")
        if not isinstance(raw_artifacts, list):
            raise ValueError("artifacts must be a list")
        artifacts: dict[str, tuple[Path, str]] = {}
        for index, raw_artifact in enumerate(raw_artifacts):
            artifact = _mapping(raw_artifact, f"artifact {index}")
            role = str(artifact.get("role", "")).strip()
            if not role or role in artifacts:
                errors.append(f"duplicate_or_missing_artifact_role:{validation_id}:{role}")
                continue
            path = _resolve_file(
                artifact.get("path"), repository_root, f"artifact {role}"
            )
            expected_hash = str(artifact.get("sha256", ""))
            if not _SHA256.fullmatch(expected_hash):
                errors.append(f"invalid_sha256:{validation_id}:{role}")
            observed_hash = _sha256(path)
            if observed_hash != expected_hash:
                errors.append(f"sha256_mismatch:{validation_id}:{role}")
            expected_bytes = artifact.get("bytes")
            if (
                isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or path.stat().st_size != expected_bytes
            ):
                errors.append(f"bytes_mismatch:{validation_id}:{role}")
            artifacts[role] = (path, expected_hash)
        missing_roles = sorted(_REQUIRED_ARTIFACT_ROLES - artifacts.keys())
        for role in missing_roles:
            errors.append(f"missing_artifact_role:{validation_id}:{role}")
        for role in sorted(artifacts.keys() - _REQUIRED_ARTIFACT_ROLES):
            if not role.startswith(_DEPENDENCY_ROLE_PREFIX):
                errors.append(f"unexpected_artifact_role:{validation_id}:{role}")
        declared_source_hash = str(external.get("source_sha256", ""))
        if not _SHA256.fullmatch(declared_source_hash):
            errors.append(f"invalid_external_source_hash:{validation_id}")
        elif declared_source_hash != artifacts.get("external_source", (Path(), ""))[1]:
            errors.append(f"external_source_hash_mismatch:{validation_id}")
        if not _SHA256.fullmatch(str(external.get("archive_sha256", ""))):
            errors.append(f"invalid_external_archive_hash:{validation_id}")
        source_url = str(external.get("source_url", ""))
        if commit and f"/blob/{commit}/" not in source_url:
            errors.append(f"source_url_commit_mismatch:{validation_id}")

        if "comparison_results" not in artifacts:
            return (
                errors,
                method_id,
                official,
                fixture_count,
                maximum_error,
                source_url,
                repository_url,
                validation_id,
                track,
            )
        result = _mapping(
            json.loads(artifacts["comparison_results"][0].read_text(encoding="utf-8")),
            "comparison results",
        )
        if result.get("schema_version") != "1.0" or result.get(
            "result_kind"
        ) != "external_implementation_comparison":
            errors.append(f"invalid_comparison_result_schema:{validation_id}")
        environment = result.get("execution_environment")
        if not isinstance(environment, Mapping) or "python" not in environment:
            errors.append(f"missing_execution_environment:{validation_id}")
        elif any(
            not str(value).strip() for value in environment.values()
        ):
            errors.append(f"incomplete_execution_environment:{validation_id}")
        if not str(result.get("source_execution", "")).strip():
            errors.append(f"missing_source_execution_boundary:{validation_id}")
        if result.get("validation_id") != validation_id:
            errors.append(f"result_validation_id_mismatch:{validation_id}")
        if result.get("method_id") != method_id:
            errors.append(f"result_method_id_mismatch:{validation_id}")
        if result.get("external_commit") != commit:
            errors.append(f"result_commit_mismatch:{validation_id}")
        source_hash = artifacts.get("external_source", (Path(), ""))[1]
        if result.get("executed_source_sha256") != source_hash:
            errors.append(f"result_source_mismatch:{validation_id}")
        executed_sources = result.get("executed_source_files")
        if executed_sources is not None:
            if not isinstance(executed_sources, Mapping):
                errors.append(f"invalid_executed_source_files:{validation_id}")
            else:
                source_roles = {
                    role
                    for role in artifacts
                    if role == "external_source"
                    or role.startswith(_DEPENDENCY_ROLE_PREFIX)
                }
                declared_roles = {str(role) for role in executed_sources}
                if declared_roles != source_roles:
                    errors.append(f"executed_source_roles_mismatch:{validation_id}")
                for role in sorted(source_roles & declared_roles):
                    if str(executed_sources[role]) != artifacts[role][1]:
                        errors.append(
                            f"executed_source_hash_mismatch:{validation_id}:{role}"
                        )
        tolerance = _float(result.get("tolerance"), "tolerance")
        if tolerance < 0:
            errors.append(f"negative_tolerance:{validation_id}")
        comparisons = result.get("comparisons")
        if not isinstance(comparisons, list):
            raise ValueError("comparisons must be a list")
        fixture_count = len(comparisons)
        if fixture_count < minimum_fixtures:
            errors.append(
                f"insufficient_fixtures:{validation_id}:{fixture_count}<{minimum_fixtures}"
            )
        observed_case_ids: set[str] = set()
        computed_maximum = 0.0
        for index, raw_comparison in enumerate(comparisons):
            comparison = _mapping(raw_comparison, f"comparison {index}")
            case_id = str(comparison.get("case_id", "")).strip()
            if not case_id or case_id in observed_case_ids:
                errors.append(f"invalid_case_id:{validation_id}:{case_id or index}")
                continue
            observed_case_ids.add(case_id)
            local = comparison.get("local_scores")
            external_scores = comparison.get("external_scores")
            if (
                not isinstance(local, list)
                or not isinstance(external_scores, list)
                or not local
                or len(local) != len(external_scores)
            ):
                errors.append(f"invalid_score_vectors:{validation_id}:{case_id}")
                continue
            local_values = [_float(value, "local score") for value in local]
            external_values = [
                _float(value, "external score") for value in external_scores
            ]
            observable_names = comparison.get("observable_names")
            if observable_names is not None and (
                not isinstance(observable_names, list)
                or len(observable_names) != len(local_values)
                or any(not str(name).strip() for name in observable_names)
            ):
                errors.append(f"invalid_observable_names:{validation_id}:{case_id}")
            expected_scores = comparison.get("expected_scores")
            if expected_scores is not None:
                if (
                    not isinstance(expected_scores, list)
                    or len(expected_scores) != len(local_values)
                ):
                    errors.append(
                        f"invalid_expected_scores:{validation_id}:{case_id}"
                    )
                else:
                    expected_values = [
                        _float(value, "expected score") for value in expected_scores
                    ]
                    if any(
                        abs(observed - expected) > tolerance
                        for observed, expected in zip(
                            local_values, expected_values, strict=True
                        )
                    ) or any(
                        abs(observed - expected) > tolerance
                        for observed, expected in zip(
                            external_values, expected_values, strict=True
                        )
                    ):
                        errors.append(
                            f"fixture_oracle_disagreement:{validation_id}:{case_id}"
                        )
            case_maximum = max(
                abs(local_value - external_value)
                for local_value, external_value in zip(
                    local_values, external_values, strict=True
                )
            )
            computed_maximum = max(computed_maximum, case_maximum)
            declared_case_maximum = _float(
                comparison.get("maximum_absolute_error"), "case maximum error"
            )
            if not math.isclose(
                declared_case_maximum, case_maximum, rel_tol=0.0, abs_tol=1e-15
            ):
                errors.append(f"case_error_mismatch:{validation_id}:{case_id}")
            if case_maximum > tolerance:
                errors.append(f"score_disagreement:{validation_id}:{case_id}")
        errors.extend(
            _audit_boundary_comparisons(
                result,
                validation_id,
                tolerance,
                observed_case_ids,
            )
        )
        maximum_error = computed_maximum
        declared_maximum = _float(
            result.get("maximum_absolute_error"), "maximum absolute error"
        )
        if not math.isclose(
            declared_maximum, computed_maximum, rel_tol=0.0, abs_tol=1e-15
        ):
            errors.append(f"maximum_error_mismatch:{validation_id}")
        if result.get("all_close") is not True:
            errors.append(f"all_close_not_true:{validation_id}")
        if computed_maximum > tolerance:
            errors.append(f"maximum_error_exceeds_tolerance:{validation_id}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_external_validation_record:{validation_id}:{exc}")
    return (
        errors,
        method_id,
        official,
        fixture_count,
        maximum_error,
        source_url,
        repository_url,
        validation_id,
        track,
    )


def audit_external_implementation_records(
    record_paths: Iterable[str | Path],
    repository_root: str | Path,
    *,
    expected_method_ids: set[str],
    minimum_records: int,
    minimum_fixtures: int,
    minimum_methods: int = 1,
    minimum_sources: int = 1,
    minimum_repositories: int = 1,
    minimum_tracks: int = 1,
) -> dict[str, Any]:
    """Verify byte-bound upstream comparisons and recompute every score delta."""

    paths = tuple(record_paths)
    root = Path(repository_root)
    errors: list[str] = []
    methods: set[str] = set()
    official_count = 0
    external_sources: set[str] = set()
    external_repositories: set[str] = set()
    tracks: set[str] = set()
    validation_ids: set[str] = set()
    resolved_record_paths: set[Path] = set()
    valid_record_count = 0
    fixture_count = 0
    maximum_error = 0.0
    for index, raw_path in enumerate(paths):
        try:
            path = _resolve_file(raw_path, root, f"external validation record {index}")
        except ValueError as exc:
            errors.append(f"invalid_external_validation_path:{raw_path}:{exc}")
            continue
        resolved_path = path.resolve()
        if resolved_path in resolved_record_paths:
            errors.append(f"duplicate_record_path:{raw_path}")
            continue
        resolved_record_paths.add(resolved_path)
        (
            record_errors,
            method_id,
            official,
            fixtures,
            observed_maximum,
            source_url,
            repository_url,
            validation_id,
            track,
        ) = _audit_record(path, root, expected_method_ids, minimum_fixtures)
        if validation_id in validation_ids:
            record_errors.append(f"duplicate_validation_id:{validation_id}")
        else:
            validation_ids.add(validation_id)
        errors.extend(record_errors)
        if record_errors:
            continue
        valid_record_count += 1
        if method_id is not None:
            methods.add(method_id)
        official_count += int(official)
        if source_url:
            external_sources.add(source_url)
        if repository_url:
            external_repositories.add(repository_url)
        if track:
            tracks.add(track)
        fixture_count += fixtures
        maximum_error = max(maximum_error, observed_maximum)
    if valid_record_count < minimum_records:
        errors.append(f"insufficient_records:{valid_record_count}<{minimum_records}")
    if len(methods) < minimum_methods:
        errors.append(f"insufficient_methods:{len(methods)}<{minimum_methods}")
    if len(external_sources) < minimum_sources:
        errors.append(
            f"insufficient_external_sources:{len(external_sources)}<{minimum_sources}"
        )
    if len(external_repositories) < minimum_repositories:
        errors.append(
            "insufficient_external_repositories:"
            f"{len(external_repositories)}<{minimum_repositories}"
        )
    if len(tracks) < minimum_tracks:
        errors.append(f"insufficient_tracks:{len(tracks)}<{minimum_tracks}")
    if not paths:
        status = "not_evidenced"
    else:
        status = "fail" if errors else "pass"
    return {
        "passed": status == "pass",
        "status": status,
        "record_count": len(paths),
        "distinct_record_count": len(resolved_record_paths),
        "valid_record_count": valid_record_count,
        "validated_method_ids": sorted(methods),
        "distinct_method_count": len(methods),
        "tracks": sorted(tracks),
        "track_count": len(tracks),
        "official_upstream_count": official_count,
        "unique_external_source_count": len(external_sources),
        "unique_external_repository_count": len(external_repositories),
        "fixture_count": fixture_count,
        "maximum_absolute_error": maximum_error,
        "errors": errors,
    }


__all__ = ["audit_external_implementation_records"]
