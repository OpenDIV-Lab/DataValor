"""Fail-closed scientific and artifact reproduction contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import BenchmarkResult
from .report import load_jsonl_results

SCIENTIFIC_DIGEST_SCHEMA = "datamechbench-scientific-results-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HTTPS_URL = re.compile(r"https://[^\s<>{}]+")
_CLEAN_ROOM_TRACKS = frozenset({"valuation", "procurement", "trading"})
_ISOLATION_MODES = frozenset({"fresh_venv"})
_RUNTIME_BEARING_ROLES = frozenset({
    "scientific_results",
    "confirmatory_evidence",
    "headline_table",
    "setting_table",
    "metric_statistics",
    "replication_scientific_results",
    "replication_evidence",
    "replication_metric_statistics",
    "replication_execution_report",
    "replication_track_summary",
    "replication_manifest",
})
_PUBLIC_PREFLIGHT_ROOT = "."
_PUBLIC_LOCK_PATH = "benchmark/reproduction/requirements-cpu.lock"


@dataclass(frozen=True)
class ArtifactBinding:
    path: str
    sha256: str
    role: str


@dataclass(frozen=True)
class ScientificResultsBinding:
    path: str
    sha256: str
    scientific_digest: str
    row_count: int
    status_counts: Mapping[str, int]
    track_counts: Mapping[str, int]


@dataclass(frozen=True)
class SourceTreeBinding:
    path: str
    sha256: str
    file_count: int


@dataclass(frozen=True)
class ReproductionManifest:
    schema_version: str
    release_id: str
    required_tracks: tuple[str, ...]
    scientific_results: ScientificResultsBinding
    replication_scientific_results: ScientificResultsBinding | None
    artifacts: tuple[ArtifactBinding, ...]
    source_trees: tuple[SourceTreeBinding, ...]
    source_path: str


@dataclass(frozen=True)
class ReproductionVerification:
    passed: bool
    errors: tuple[str, ...]
    verified_artifacts: int
    scientific_digest: str | None
    row_count: int
    status_counts: Mapping[str, int]
    track_counts: Mapping[str, int]
    non_scientific_differences: tuple[str, ...]


@dataclass(frozen=True)
class CleanRoomAudit:
    passed: bool
    errors: tuple[str, ...]
    valid_records: int
    operator_ids: tuple[str, ...]
    covered_tracks: tuple[str, ...]
    required_operators: int


def _scientific_record(result: BenchmarkResult) -> dict[str, object]:
    record = result.to_dict()
    record.pop("runtime_seconds", None)
    metrics = dict(record.get("metrics", {}))
    metrics.pop("runtime_seconds", None)
    record["metrics"] = metrics
    return record


def scientific_result_digest(results: Iterable[BenchmarkResult]) -> str:
    """Hash all scientific result content while excluding timing measurements."""

    records = [_scientific_record(result) for result in results]
    records.sort(
        key=lambda item: (
            str(item["track"]),
            str(item["case_id"]),
            str(item["method_id"]),
            int(item["seed"]),
            str(item["run_id"]),
        )
    )
    payload = {
        "schema": SCIENTIFIC_DIGEST_SCHEMA,
        "results": records,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): value for key, value in raw.items()}


def _canonical_sha256(raw: Any, label: str) -> str:
    value = str(raw)
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{label} sha256 must be 64 lowercase hexadecimal characters")
    return value


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        dict(payload), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _environment_preflight_errors(
    raw: Mapping[str, Any], *, expected_python: str
) -> tuple[str, ...]:
    """Return fail-closed errors for an embedded native-Python preflight."""

    payload = _mapping(raw, "environment preflight")
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("environment_preflight_schema_mismatch")
    if payload.get("report_kind") != "native_python_environment_preflight":
        errors.append("environment_preflight_kind_mismatch")
    if payload.get("passed") is not True or payload.get("errors") != []:
        errors.append("environment_preflight_not_passed")
    if (
        payload.get("runtime_kind") != "native_python_source_library"
        or payload.get("container_or_vm_image_required") is not False
    ):
        errors.append("environment_preflight_not_native")
    if payload.get("python_version") != expected_python:
        errors.append("environment_preflight_python_mismatch")
    if (
        payload.get("repository_root") != _PUBLIC_PREFLIGHT_ROOT
        or payload.get("lock_file") != _PUBLIC_LOCK_PATH
    ):
        errors.append("environment_preflight_paths_not_normalized")
    if not _SHA256.fullmatch(str(payload.get("lock_sha256", ""))):
        errors.append("environment_preflight_lock_hash_invalid")

    counts = payload.get("package_counts")
    count_map = _mapping(counts, "package_counts") if isinstance(counts, Mapping) else {}
    packages = payload.get("packages")
    package_rows = packages if isinstance(packages, list) else []
    matched = count_map.get("matched")
    if (
        count_map.get("mismatched") != 0
        or count_map.get("missing") != 0
        or isinstance(matched, bool)
        or not isinstance(matched, int)
        or matched < 1
        or matched != len(package_rows)
    ):
        errors.append("environment_preflight_packages_unmatched")
    for package in package_rows:
        if not isinstance(package, Mapping):
            errors.append("environment_preflight_packages_unmatched")
            break
        expected = str(package.get("expected", ""))
        observed = str(package.get("observed", ""))
        if package.get("status") != "matched" or not expected or observed != expected:
            errors.append("environment_preflight_packages_unmatched")
            break
    return tuple(dict.fromkeys(errors))


def _normalized_environment_preflight(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Remove operator-local paths while preserving auditable environment data."""

    payload = _mapping(raw, "environment_preflight")
    payload["repository_root"] = _PUBLIC_PREFLIGHT_ROOT
    payload["lock_file"] = _PUBLIC_LOCK_PATH
    return payload


def _environment_lock_sha256(manifest: ReproductionManifest) -> str:
    bindings = [
        binding.sha256
        for binding in manifest.artifacts
        if binding.role == "environment_lock"
    ]
    if len(bindings) != 1:
        raise ValueError("reproduction manifest must bind one environment_lock")
    return bindings[0]


def _safe_relative_path(raw: Any, root: Path, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} path must be non-empty")
    value = raw.strip()
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} path must be repository-relative")
    resolved_root = root.resolve()
    try:
        (resolved_root / candidate).resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} path escapes repository root: {value}") from exc
    return candidate.as_posix()


def resolve_repository_file(
    raw: Any,
    repository_root: str | Path,
    *,
    label: str = "artifact",
) -> Path:
    """Resolve an existing regular file without accepting host-specific paths."""

    root = Path(repository_root).resolve()
    relative = _safe_relative_path(raw, root, label)
    candidate = root / relative
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"{label} must be an existing regular non-symlink file")
    return candidate.resolve()


def _counts(raw: Any, label: str) -> dict[str, int]:
    values = _mapping(raw, label)
    counts: dict[str, int] = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label}.{key} must be a non-negative integer")
        counts[key] = value
    return counts


def load_reproduction_manifest(
    path: str | Path,
    repository_root: str | Path,
) -> ReproductionManifest:
    """Load and structurally validate a KDD core reproduction manifest."""

    source = Path(path)
    raw = _mapping(
        json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard numeric constant {value}")
            ),
        ),
        "reproduction manifest",
    )
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported reproduction manifest schema_version")
    if raw.get("manifest_kind") != "kdd_core_reproduction":
        raise ValueError("manifest_kind must be kdd_core_reproduction")
    release_id = str(raw.get("release_id", "")).strip()
    if not release_id:
        raise ValueError("release_id must be non-empty")
    tracks_raw = raw.get("required_tracks")
    if (
        not isinstance(tracks_raw, list)
        or not tracks_raw
        or any(not str(item).strip() for item in tracks_raw)
    ):
        raise ValueError("required_tracks must be a non-empty list")
    required_tracks = tuple(str(item) for item in tracks_raw)
    if len(set(required_tracks)) != len(required_tracks):
        raise ValueError("required_tracks must be unique")

    root = Path(repository_root)
    result_raw = _mapping(raw.get("scientific_results"), "scientific_results")
    row_count = result_raw.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise ValueError("scientific_results.row_count must be a non-negative integer")
    scientific_results = ScientificResultsBinding(
        path=_safe_relative_path(result_raw.get("path"), root, "scientific_results"),
        sha256=_canonical_sha256(result_raw.get("sha256"), "scientific_results"),
        scientific_digest=_canonical_sha256(
            result_raw.get("scientific_digest"), "scientific_results.scientific_digest"
        ),
        row_count=row_count,
        status_counts=_counts(result_raw.get("status_counts"), "status_counts"),
        track_counts=_counts(result_raw.get("track_counts"), "track_counts"),
    )
    replication_results: ScientificResultsBinding | None = None
    if raw.get("replication_scientific_results") is not None:
        replication_raw = _mapping(
            raw.get("replication_scientific_results"),
            "replication_scientific_results",
        )
        replication_row_count = replication_raw.get("row_count")
        if (
            isinstance(replication_row_count, bool)
            or not isinstance(replication_row_count, int)
            or replication_row_count < 0
        ):
            raise ValueError(
                "replication_scientific_results.row_count must be a non-negative integer"
            )
        replication_results = ScientificResultsBinding(
            path=_safe_relative_path(
                replication_raw.get("path"), root, "replication_scientific_results"
            ),
            sha256=_canonical_sha256(
                replication_raw.get("sha256"), "replication_scientific_results"
            ),
            scientific_digest=_canonical_sha256(
                replication_raw.get("scientific_digest"),
                "replication_scientific_results.scientific_digest",
            ),
            row_count=replication_row_count,
            status_counts=_counts(
                replication_raw.get("status_counts"),
                "replication_status_counts",
            ),
            track_counts=_counts(
                replication_raw.get("track_counts"),
                "replication_track_counts",
            ),
        )

    artifacts_raw = raw.get("artifacts")
    if not isinstance(artifacts_raw, list):
        raise ValueError("artifacts must be a list")
    artifacts: list[ArtifactBinding] = []
    for index, item in enumerate(artifacts_raw):
        value = _mapping(item, f"artifacts[{index}]")
        role = str(value.get("role", "")).strip()
        if not role:
            raise ValueError(f"artifacts[{index}].role must be non-empty")
        artifacts.append(ArtifactBinding(
            path=_safe_relative_path(value.get("path"), root, f"artifacts[{index}]"),
            sha256=_canonical_sha256(value.get("sha256"), f"artifacts[{index}]"),
            role=role,
        ))
    all_paths = [
        scientific_results.path,
        *([replication_results.path] if replication_results is not None else []),
        *(item.path for item in artifacts),
    ]
    if len(set(all_paths)) != len(all_paths):
        raise ValueError("manifest artifact paths must be unique")

    trees_raw = raw.get("source_trees")
    if not isinstance(trees_raw, list) or not trees_raw:
        raise ValueError("source_trees must be a non-empty list")
    source_trees: list[SourceTreeBinding] = []
    for index, item in enumerate(trees_raw):
        value = _mapping(item, f"source_trees[{index}]")
        file_count = value.get("file_count")
        if (
            isinstance(file_count, bool)
            or not isinstance(file_count, int)
            or file_count < 1
        ):
            raise ValueError(f"source_trees[{index}].file_count must be positive")
        source_trees.append(SourceTreeBinding(
            path=_safe_relative_path(
                value.get("path"), root, f"source_trees[{index}]"
            ),
            sha256=_canonical_sha256(value.get("sha256"), f"source_trees[{index}]"),
            file_count=file_count,
        ))
    tree_paths = [item.path for item in source_trees]
    if len(set(tree_paths)) != len(tree_paths):
        raise ValueError("source tree paths must be unique")
    return ReproductionManifest(
        schema_version="1.0",
        release_id=release_id,
        required_tracks=required_tracks,
        scientific_results=scientific_results,
        replication_scientific_results=replication_results,
        artifacts=tuple(artifacts),
        source_trees=tuple(source_trees),
        source_path=str(source),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_tree_digest(path: Path) -> tuple[str, int]:
    root = path.resolve()
    files = sorted(item for item in path.rglob("*.py") if item.is_file())
    digest = hashlib.sha256()
    for item in files:
        resolved = item.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"source tree symlink escapes root: {item}") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def verify_reproduction_manifest(
    manifest: ReproductionManifest,
    repository_root: str | Path,
    *,
    verification_mode: str = "archive",
) -> ReproductionVerification:
    """Verify bytes, scientific content, counts, and required track coverage."""

    if verification_mode not in {"archive", "reproduction"}:
        raise ValueError("verification_mode must be archive or reproduction")
    root = Path(repository_root).resolve()
    errors: list[str] = []
    non_scientific_differences: list[str] = []
    verified = 0
    bindings = (
        ArtifactBinding(
            manifest.scientific_results.path,
            manifest.scientific_results.sha256,
            "scientific_results",
        ),
        *(
            (
                ArtifactBinding(
                    manifest.replication_scientific_results.path,
                    manifest.replication_scientific_results.sha256,
                    "replication_scientific_results",
                ),
            )
            if manifest.replication_scientific_results is not None
            else ()
        ),
        *manifest.artifacts,
    )
    for binding in bindings:
        path = root / binding.path
        if not path.is_file():
            errors.append(f"missing:{binding.path}")
            continue
        observed = _file_sha256(path)
        if observed != binding.sha256:
            if (
                verification_mode == "reproduction"
                and binding.role in _RUNTIME_BEARING_ROLES
            ):
                non_scientific_differences.append(f"byte_hash:{binding.path}")
                continue
            errors.append(
                f"hash_mismatch:{binding.path}:expected={binding.sha256}:observed={observed}"
            )
            continue
        verified += 1

    for binding in manifest.source_trees:
        path = root / binding.path
        if not path.is_dir():
            errors.append(f"missing_source_tree:{binding.path}")
            continue
        try:
            observed_hash, observed_count = _source_tree_digest(path)
        except (OSError, ValueError) as exc:
            errors.append(f"invalid_source_tree:{binding.path}:{exc}")
            continue
        valid = True
        if observed_hash != binding.sha256:
            errors.append(
                f"source_tree_hash_mismatch:{binding.path}:"
                f"expected={binding.sha256}:observed={observed_hash}"
            )
            valid = False
        if observed_count != binding.file_count:
            errors.append(
                f"source_tree_count_mismatch:{binding.path}:"
                f"expected={binding.file_count}:observed={observed_count}"
            )
            valid = False
        if valid:
            verified += 1

    results_path = root / manifest.scientific_results.path
    digest: str | None = None
    rows: tuple[BenchmarkResult, ...] = ()
    if results_path.is_file():
        try:
            rows = load_jsonl_results(results_path)
            digest = scientific_result_digest(rows)
        except (OSError, ValueError) as exc:
            errors.append(f"invalid_results:{manifest.scientific_results.path}:{exc}")
    if digest is not None and digest != manifest.scientific_results.scientific_digest:
        errors.append(
            "scientific_digest_mismatch:"
            f"{manifest.scientific_results.path}:"
            f"expected={manifest.scientific_results.scientific_digest}:observed={digest}"
        )
    row_count = len(rows)
    if row_count != manifest.scientific_results.row_count:
        errors.append(
            f"row_count_mismatch:expected={manifest.scientific_results.row_count}:"
            f"observed={row_count}"
        )
    status_counts = dict(sorted(Counter(row.status for row in rows).items()))
    track_counts = dict(sorted(Counter(row.track for row in rows).items()))
    if status_counts != dict(manifest.scientific_results.status_counts):
        errors.append(
            "status_counts_mismatch:"
            f"expected={dict(manifest.scientific_results.status_counts)}:"
            f"observed={status_counts}"
        )
    if track_counts != dict(manifest.scientific_results.track_counts):
        errors.append(
            "track_counts_mismatch:"
            f"expected={dict(manifest.scientific_results.track_counts)}:"
            f"observed={track_counts}"
        )
    missing_tracks = sorted(set(manifest.required_tracks) - set(track_counts))
    if missing_tracks:
        errors.append("missing_required_tracks:" + ",".join(missing_tracks))

    replication = manifest.replication_scientific_results
    if replication is not None:
        replication_path = root / replication.path
        replication_rows: tuple[BenchmarkResult, ...] = ()
        replication_digest: str | None = None
        if replication_path.is_file():
            try:
                replication_rows = load_jsonl_results(replication_path)
                replication_digest = scientific_result_digest(replication_rows)
            except (OSError, ValueError) as exc:
                errors.append(f"invalid_replication_results:{replication.path}:{exc}")
        if replication_digest != replication.scientific_digest:
            errors.append(
                "replication_scientific_digest_mismatch:"
                f"{replication.path}:expected={replication.scientific_digest}:"
                f"observed={replication_digest}"
            )
        if len(replication_rows) != replication.row_count:
            errors.append(
                "replication_row_count_mismatch:"
                f"expected={replication.row_count}:observed={len(replication_rows)}"
            )
        replication_status = dict(
            sorted(Counter(row.status for row in replication_rows).items())
        )
        replication_tracks = dict(
            sorted(Counter(row.track for row in replication_rows).items())
        )
        if replication_status != dict(replication.status_counts):
            errors.append("replication_status_counts_mismatch")
        if replication_tracks != dict(replication.track_counts):
            errors.append("replication_track_counts_mismatch")
        replication_missing = sorted(
            set(manifest.required_tracks) - set(replication_tracks)
        )
        if replication_missing:
            errors.append(
                "replication_missing_required_tracks:" + ",".join(replication_missing)
            )
    return ReproductionVerification(
        passed=not errors,
        errors=tuple(errors),
        verified_artifacts=verified,
        scientific_digest=digest,
        row_count=row_count,
        status_counts=status_counts,
        track_counts=track_counts,
        non_scientific_differences=tuple(non_scientific_differences),
    )


def create_clean_room_record(
    manifest_path: str | Path,
    repository_root: str | Path,
    *,
    operator_id: str,
    independent_of_implementation: bool,
    isolation: str,
    os_description: str,
    python_version: str,
    command: str,
    exit_code: int,
    setup_minutes: float,
    artifact_verification_passed: bool,
    observed_scientific_digest: str | None,
    operator_confirmed: bool,
    no_source_modifications: bool,
    unexpected_differences: Iterable[str],
    source_archive_url: str,
    source_archive_sha256: str,
    environment_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a fail-closed operator attestation for one exact core release."""

    root = Path(repository_root).resolve()
    relative = _safe_relative_path(manifest_path, root, "expected_manifest")
    manifest_file = root / relative
    manifest = load_reproduction_manifest(manifest_file, root)
    clean_operator_id = str(operator_id).strip()
    if not clean_operator_id or clean_operator_id.startswith("<"):
        raise ValueError("operator_id must be a non-placeholder identifier")
    if isolation not in _ISOLATION_MODES:
        raise ValueError(f"unsupported isolation mode: {isolation}")
    if not str(os_description).strip():
        raise ValueError("os_description must be non-empty")
    if not str(python_version).strip():
        raise ValueError("python_version must be non-empty")
    if not str(command).strip():
        raise ValueError("command must be non-empty")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError("exit_code must be an integer")
    if (
        isinstance(setup_minutes, bool)
        or not isinstance(setup_minutes, (int, float))
        or setup_minutes < 0
    ):
        raise ValueError("setup_minutes must be a non-negative number")
    differences = tuple(str(value).strip() for value in unexpected_differences)
    if any(not value for value in differences):
        raise ValueError("unexpected differences must be non-empty strings")
    clean_archive_url = str(source_archive_url).strip()
    if not _HTTPS_URL.fullmatch(clean_archive_url):
        raise ValueError("source_archive_url must be a non-placeholder HTTPS URL")
    clean_archive_sha256 = _canonical_sha256(
        source_archive_sha256, "source_archive"
    )
    preflight = _normalized_environment_preflight(environment_preflight)
    preflight_errors = _environment_preflight_errors(
        preflight, expected_python=str(python_version).strip()
    )
    expected_lock_sha256 = _environment_lock_sha256(manifest)
    if preflight.get("lock_sha256") != expected_lock_sha256:
        preflight_errors = (
            *preflight_errors,
            "environment_preflight_lock_hash_mismatch",
        )

    expected_digest = manifest.scientific_results.scientific_digest
    machine_passed = (
        exit_code == 0
        and artifact_verification_passed is True
        and observed_scientific_digest == expected_digest
        and not preflight_errors
    )
    attestation_complete = (
        operator_confirmed is True
        and independent_of_implementation is True
        and no_source_modifications is True
        and not differences
    )
    status = "passed" if machine_passed and attestation_complete else (
        "failed" if not machine_passed else "draft"
    )
    return {
        "schema_version": "1.1",
        "record_kind": "clean_room_reproduction",
        "status": status,
        "operator": {
            "operator_id": clean_operator_id,
            "independent_of_implementation": bool(independent_of_implementation),
        },
        "environment": {
            "isolation": isolation,
            "os": str(os_description).strip(),
            "python": str(python_version).strip(),
            "preflight": preflight,
            "preflight_sha256": _canonical_json_sha256(preflight),
        },
        "execution": {
            "command": str(command).strip(),
            "exit_code": exit_code,
            "setup_minutes": float(setup_minutes),
        },
        "release": {
            "manifest_path": relative,
            "manifest_sha256": _file_sha256(manifest_file),
            "scientific_digest": observed_scientific_digest or "",
            "artifact_verification": (
                "passed" if artifact_verification_passed is True else "failed"
            ),
            "source_archive": {
                "url": clean_archive_url,
                "sha256": clean_archive_sha256,
            },
        },
        "tracks": list(manifest.required_tracks),
        "attestation": {
            "operator_confirmed": bool(operator_confirmed),
            "no_source_modifications": bool(no_source_modifications),
            "unexpected_differences": list(differences),
        },
    }


def audit_clean_room_records(
    paths: Iterable[str],
    repository_root: str | Path,
    expected_manifest_path: str,
    *,
    required_operators: int,
    expected_archive_url: str,
    expected_archive_sha256: str,
) -> CleanRoomAudit:
    """Validate independent reproduction attestations against one exact release."""

    if required_operators < 1:
        raise ValueError("required_operators must be positive")
    clean_expected_url = str(expected_archive_url).strip()
    if not _HTTPS_URL.fullmatch(clean_expected_url):
        raise ValueError("expected_archive_url must be a non-placeholder HTTPS URL")
    clean_expected_sha256 = _canonical_sha256(
        expected_archive_sha256, "expected_archive"
    )
    root = Path(repository_root).resolve()
    manifest_relative = _safe_relative_path(
        expected_manifest_path, root, "expected_manifest"
    )
    manifest_path = root / manifest_relative
    manifest = load_reproduction_manifest(manifest_path, root)
    expected_manifest_hash = _file_sha256(manifest_path)
    expected_digest = manifest.scientific_results.scientific_digest
    expected_lock_sha256 = _environment_lock_sha256(manifest)
    errors: list[str] = []
    operators: set[str] = set()
    covered_tracks: set[str] = set()
    valid_records = 0

    for raw_path in paths:
        try:
            relative = _safe_relative_path(raw_path, root, "clean_room_record")
        except ValueError as exc:
            errors.append(f"invalid_record_path:{raw_path}:{exc}")
            continue
        path = root / relative
        if not path.is_file():
            errors.append(f"missing_record:{relative}")
            continue
        try:
            record = _mapping(
                json.loads(
                    path.read_text(encoding="utf-8"),
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"non-standard numeric constant {value}")
                    ),
                ),
                f"clean_room_record:{relative}",
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid_record:{relative}:{exc}")
            continue
        record_errors: list[str] = []
        if record.get("schema_version") != "1.1":
            record_errors.append("unsupported_schema_version")
        if record.get("record_kind") != "clean_room_reproduction":
            record_errors.append("wrong_record_kind")
        if record.get("status") != "passed":
            record_errors.append("record_not_passed")

        operator = record.get("operator")
        operator_map = _mapping(operator, "operator") if isinstance(operator, Mapping) else {}
        operator_id = str(operator_map.get("operator_id", "")).strip()
        if not operator_id or operator_id.startswith("<"):
            record_errors.append("invalid_operator_id")
        if operator_map.get("independent_of_implementation") is not True:
            record_errors.append("operator_not_independent")
        if operator_id in operators:
            record_errors.append(f"duplicate_operator:{operator_id}")

        environment = record.get("environment")
        environment_map = (
            _mapping(environment, "environment")
            if isinstance(environment, Mapping) else {}
        )
        if environment_map.get("isolation") not in _ISOLATION_MODES:
            record_errors.append("invalid_isolation")
        preflight = environment_map.get("preflight")
        if not isinstance(preflight, Mapping):
            record_errors.append("missing_environment_preflight")
        else:
            record_errors.extend(
                _environment_preflight_errors(
                    preflight,
                    expected_python=str(environment_map.get("python", "")).strip(),
                )
            )
            if environment_map.get("preflight_sha256") != _canonical_json_sha256(
                preflight
            ):
                record_errors.append("environment_preflight_hash_mismatch")
            if preflight.get("lock_sha256") != expected_lock_sha256:
                record_errors.append("environment_preflight_lock_hash_mismatch")

        execution = record.get("execution")
        execution_map = _mapping(execution, "execution") if isinstance(execution, Mapping) else {}
        if not str(execution_map.get("command", "")).strip():
            record_errors.append("missing_command")
        if execution_map.get("exit_code") != 0:
            record_errors.append("nonzero_exit_code")
        setup_minutes = execution_map.get("setup_minutes")
        if (
            isinstance(setup_minutes, bool)
            or not isinstance(setup_minutes, (int, float))
            or setup_minutes < 0
        ):
            record_errors.append("invalid_setup_minutes")

        release = record.get("release")
        release_map = _mapping(release, "release") if isinstance(release, Mapping) else {}
        if release_map.get("manifest_path") != manifest_relative:
            record_errors.append("manifest_path_mismatch")
        if release_map.get("manifest_sha256") != expected_manifest_hash:
            record_errors.append("manifest_hash_mismatch")
        if release_map.get("scientific_digest") != expected_digest:
            record_errors.append("scientific_digest_mismatch")
        if release_map.get("artifact_verification") != "passed":
            record_errors.append("artifact_verification_not_passed")
        source_archive = release_map.get("source_archive")
        source_archive_map = (
            _mapping(source_archive, "source_archive")
            if isinstance(source_archive, Mapping)
            else {}
        )
        if source_archive_map.get("url") != clean_expected_url:
            record_errors.append("source_archive_url_mismatch")
        if source_archive_map.get("sha256") != clean_expected_sha256:
            record_errors.append("source_archive_hash_mismatch")

        tracks_raw = record.get("tracks")
        tracks = {
            str(track) for track in tracks_raw
        } if isinstance(tracks_raw, list) else set()
        missing_tracks = sorted(_CLEAN_ROOM_TRACKS - tracks)
        if missing_tracks:
            record_errors.append("missing_tracks:" + ",".join(missing_tracks))

        attestation = record.get("attestation")
        attestation_map = (
            _mapping(attestation, "attestation")
            if isinstance(attestation, Mapping) else {}
        )
        differences = attestation_map.get("unexpected_differences")
        if (
            attestation_map.get("operator_confirmed") is not True
            or attestation_map.get("no_source_modifications") is not True
            or not isinstance(differences, list)
            or differences
        ):
            record_errors.append("invalid_attestation")

        if record_errors:
            errors.extend(f"{relative}:{error}" for error in record_errors)
            if operator_id in operators:
                errors.append(f"duplicate_operator:{operator_id}")
            continue
        operators.add(operator_id)
        covered_tracks.update(tracks & _CLEAN_ROOM_TRACKS)
        valid_records += 1

    if len(operators) < required_operators:
        errors.append(
            "insufficient_independent_operators:"
            f"required={required_operators}:observed={len(operators)}"
        )
    return CleanRoomAudit(
        passed=not errors,
        errors=tuple(dict.fromkeys(errors)),
        valid_records=valid_records,
        operator_ids=tuple(sorted(operators)),
        covered_tracks=tuple(sorted(covered_tracks)),
        required_operators=required_operators,
    )


__all__ = [
    "ArtifactBinding",
    "CleanRoomAudit",
    "ReproductionManifest",
    "ReproductionVerification",
    "SCIENTIFIC_DIGEST_SCHEMA",
    "ScientificResultsBinding",
    "SourceTreeBinding",
    "audit_clean_room_records",
    "create_clean_room_record",
    "load_reproduction_manifest",
    "resolve_repository_file",
    "scientific_result_digest",
    "verify_reproduction_manifest",
]
