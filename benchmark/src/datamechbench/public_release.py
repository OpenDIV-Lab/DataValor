"""Deterministic, non-extracting public-release candidate packaging."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .reproduction import load_reproduction_manifest, verify_reproduction_manifest

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DEFAULT_REPRODUCTION_MANIFEST = PACKAGE_ROOT / "reproduction" / "kdd2027_core_manifest.json"
DEFAULT_ARCHIVE = PACKAGE_ROOT / "dist" / "datamechbench-kdd2027-core.tar.gz"
DEFAULT_SIDECAR = PACKAGE_ROOT / "dist" / "datamechbench-kdd2027-core.manifest.json"
DEFAULT_EXTRA_PATHS = (
    REPOSITORY_ROOT / "LICENSE",
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "pyproject.toml",
    PACKAGE_ROOT / "README.md",
    PACKAGE_ROOT / "pyproject.toml",
    PACKAGE_ROOT / "reproduction" / "README.md",
    PACKAGE_ROOT / "docs" / "kdd_heldout_findings.md",
    PACKAGE_ROOT / "docs" / "governance_and_ethics.md",
    PACKAGE_ROOT / "catalog" / "kdd_public_release.yaml",
    PACKAGE_ROOT / "catalog" / "qualification.yaml",
)
_SAFE_RELEASE_ID = re.compile(r"[A-Za-z0-9._-]+")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_relative(path: Path, root: Path, label: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be inside repository root: {path}") from exc
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file: {path}")
    return relative.as_posix()


def _safe_member_path(raw: str) -> bool:
    if not raw or "\\" in raw:
        return False
    path = PurePosixPath(raw)
    return (
        not path.is_absolute()
        and path.as_posix() == raw
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _member_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _input_paths(
    repository_root: Path,
    reproduction_manifest: Path,
    extra_paths: Iterable[str | Path],
) -> tuple[Any, dict[str, Path]]:
    manifest = load_reproduction_manifest(reproduction_manifest, repository_root)
    verification = verify_reproduction_manifest(manifest, repository_root)
    if not verification.passed:
        raise ValueError(
            "reproduction manifest does not verify: " + ";".join(verification.errors)
        )
    paths: dict[str, Path] = {}

    def add(path: Path, label: str) -> None:
        relative = _repository_relative(path, repository_root, label)
        if relative in paths:
            if paths[relative].resolve() == path.resolve():
                return
            raise ValueError(f"conflicting release input: {relative}")
        paths[relative] = path

    add(reproduction_manifest, "reproduction manifest")
    add(repository_root / manifest.scientific_results.path, "scientific results")
    if manifest.replication_scientific_results is not None:
        add(
            repository_root / manifest.replication_scientific_results.path,
            "replication scientific results",
        )
    for binding in manifest.artifacts:
        add(repository_root / binding.path, f"artifact {binding.path}")
    for binding in manifest.source_trees:
        tree = repository_root / binding.path
        for path in sorted(tree.rglob("*.py")):
            add(path, f"source tree {binding.path}")
    for raw in extra_paths:
        add(Path(raw), "extra release document")
    return manifest, paths


def build_release_candidate(
    repository_root: str | Path,
    reproduction_manifest: str | Path,
    archive_path: str | Path,
    sidecar_path: str | Path,
    *,
    extra_paths: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Build a byte-deterministic tar.gz and its external verification manifest."""

    root = Path(repository_root).resolve()
    reproduction_path = Path(reproduction_manifest).resolve()
    archive = Path(archive_path)
    sidecar = Path(sidecar_path)
    if archive.resolve() == sidecar.resolve():
        raise ValueError("archive and sidecar paths must differ")
    manifest, inputs = _input_paths(root, reproduction_path, extra_paths)
    if not _SAFE_RELEASE_ID.fullmatch(manifest.release_id):
        raise ValueError("release_id contains archive-unsafe characters")
    output_paths = {archive.resolve(), sidecar.resolve()}
    if any(path.resolve() in output_paths for path in inputs.values()):
        raise ValueError("archive or sidecar cannot also be a release input")
    prefix = f"DataMechBench-{manifest.release_id}"
    payloads = {
        f"{prefix}/{relative}": path.read_bytes()
        for relative, path in sorted(inputs.items())
    }
    reproduction_relative = _repository_relative(
        reproduction_path, root, "reproduction manifest"
    )
    release_metadata = {
        "schema_version": "1.0",
        "release_id": manifest.release_id,
        "scientific_digest": manifest.scientific_results.scientific_digest,
        "scientific_row_count": manifest.scientific_results.row_count,
        "required_tracks": list(manifest.required_tracks),
        "reproduction_manifest": reproduction_relative,
        "reproduction_manifest_sha256": _sha256_file(reproduction_path),
        "entry_count": len(payloads) + 1,
        "claim_boundary": (
            "Internal integrity and reproducibility evidence only; DOI, public "
            "availability and independent reproduction "
            "require external records."
        ),
    }
    metadata_name = f"{prefix}/RELEASE-METADATA.json"
    payloads[metadata_name] = (
        json.dumps(release_metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    archive.parent.mkdir(parents=True, exist_ok=True)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as tar:
                for name, payload in sorted(payloads.items()):
                    tar.addfile(_member_info(name, len(payload)), io.BytesIO(payload))
    entries = [
        {"path": name, "sha256": _sha256_bytes(payload), "bytes": len(payload)}
        for name, payload in sorted(payloads.items())
    ]
    result = {
        "schema_version": "1.0",
        "manifest_kind": "kdd_public_release_candidate",
        "release_id": manifest.release_id,
        "generation_command": (
            "PYTHONPATH=benchmark/src:src python "
            "benchmark/scripts/build_kdd_release_candidate.py --build"
        ),
        "reproduction": {
            "release_id": manifest.release_id,
            "path": reproduction_relative,
            "sha256": _sha256_file(reproduction_path),
            "scientific_digest": manifest.scientific_results.scientific_digest,
            "scientific_row_count": manifest.scientific_results.row_count,
        },
        "archive": {
            "path": archive.name,
            "sha256": _sha256_file(archive),
            "bytes": archive.stat().st_size,
        },
        "entry_count": len(entries),
        "entries": entries,
    }
    sidecar.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def verify_release_candidate(
    sidecar_path: str | Path,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify archive bytes and members without extracting untrusted paths."""

    sidecar = Path(sidecar_path)
    errors: list[str] = []
    try:
        manifest = json.loads(
            sidecar.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard numeric constant {value}")
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_sidecar:{exc}"], "entry_count": 0}
    if manifest.get("schema_version") != "1.0" or manifest.get("manifest_kind") != "kdd_public_release_candidate":
        errors.append("invalid_sidecar_schema")
    raw_reproduction_record = manifest.get("reproduction", {})
    if not isinstance(raw_reproduction_record, dict):
        errors.append("invalid_reproduction_record")
        reproduction_record: dict[str, Any] = {}
    else:
        reproduction_record = raw_reproduction_record
    reproduction_path = str(reproduction_record.get("path", ""))
    if not _safe_member_path(reproduction_path):
        errors.append("unsafe_reproduction_manifest_path")
    elif repository_root is not None:
        repository_manifest = Path(repository_root).resolve() / reproduction_path
        if not repository_manifest.is_file() or repository_manifest.is_symlink():
            errors.append(f"missing_repository_reproduction_manifest:{reproduction_path}")
        elif _sha256_file(repository_manifest) != reproduction_record.get("sha256"):
            errors.append(
                "repository_reproduction_manifest_sha256_mismatch:"
                f"{reproduction_path}"
            )
    archive_record = manifest.get("archive", {})
    archive_relative = Path(str(archive_record.get("path", "")))
    if archive_relative.is_absolute() or archive_relative.name != archive_relative.as_posix():
        errors.append("unsafe_archive_path")
        return {"valid": False, "errors": errors, "entry_count": 0}
    archive = sidecar.parent / archive_relative
    if not archive.is_file():
        errors.append("missing_archive")
        return {"valid": False, "errors": errors, "entry_count": 0}
    if _sha256_file(archive) != archive_record.get("sha256"):
        errors.append("archive_sha256_mismatch")
        return {"valid": False, "errors": errors, "entry_count": 0}
    if archive.stat().st_size != archive_record.get("bytes"):
        errors.append("archive_size_mismatch")
    entries_raw = manifest.get("entries", ())
    if not isinstance(entries_raw, list):
        errors.append("entries_not_list")
        entries_raw = []
    expected: dict[str, dict[str, Any]] = {}
    for entry in entries_raw:
        name = str(entry.get("path", ""))
        if not _safe_member_path(name):
            errors.append(f"unsafe_manifest_member_path:{name}")
        if name in expected:
            errors.append(f"duplicate_manifest_member:{name}")
        expected[name] = dict(entry)
    release_id = str(manifest.get("release_id", ""))
    if not _SAFE_RELEASE_ID.fullmatch(release_id):
        errors.append("invalid_release_id")
    elif _safe_member_path(reproduction_path):
        reproduction_member = f"DataMechBench-{release_id}/{reproduction_path}"
        reproduction_binding = expected.get(reproduction_member)
        if reproduction_binding is None:
            errors.append("missing_release_reproduction_manifest_entry")
        elif reproduction_binding.get("sha256") != reproduction_record.get("sha256"):
            errors.append("release_reproduction_manifest_entry_sha256_mismatch")
    observed: dict[str, bytes] = {}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                if not _safe_member_path(name):
                    errors.append(f"unsafe_member_path:{name}")
                if name in observed:
                    errors.append(f"duplicate_archive_member:{name}")
                if not member.isfile():
                    errors.append(f"non_regular_member:{name}")
                    continue
                if (
                    member.mtime != 0
                    or member.uid != 0
                    or member.gid != 0
                    or member.uname != ""
                    or member.gname != ""
                    or member.mode != 0o644
                ):
                    errors.append(f"non_normalized_metadata:{name}")
                stream = tar.extractfile(member)
                if stream is None:
                    errors.append(f"unreadable_member:{name}")
                    continue
                observed[name] = stream.read()
    except (OSError, tarfile.TarError) as exc:
        errors.append(f"invalid_archive:{exc}")
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    errors.extend(f"missing_member:{name}" for name in missing)
    errors.extend(f"unexpected_member:{name}" for name in extra)
    for name in sorted(set(expected) & set(observed)):
        payload = observed[name]
        if len(payload) != expected[name].get("bytes"):
            errors.append(f"member_size_mismatch:{name}")
        if _sha256_bytes(payload) != expected[name].get("sha256"):
            errors.append(f"member_sha256_mismatch:{name}")
    if manifest.get("entry_count") != len(expected):
        errors.append("sidecar_entry_count_mismatch")
    if len(observed) != len(expected):
        errors.append("archive_entry_count_mismatch")
    metadata_names = [name for name in observed if name.endswith("/RELEASE-METADATA.json")]
    if len(metadata_names) != 1:
        errors.append("missing_unique_release_metadata")
    else:
        try:
            metadata = json.loads(observed[metadata_names[0]].decode("utf-8"))
            reproduction = manifest.get("reproduction", {})
            if metadata.get("release_id") != manifest.get("release_id"):
                errors.append("release_metadata_id_mismatch")
            if metadata.get("scientific_digest") != reproduction.get("scientific_digest"):
                errors.append("release_metadata_scientific_digest_mismatch")
            if metadata.get("reproduction_manifest") != reproduction_path:
                errors.append("release_metadata_reproduction_manifest_path_mismatch")
            if metadata.get("reproduction_manifest_sha256") != reproduction.get("sha256"):
                errors.append(
                    "release_metadata_reproduction_manifest_sha256_mismatch"
                )
            if metadata.get("entry_count") != len(expected):
                errors.append("release_metadata_entry_count_mismatch")
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append("invalid_release_metadata")
    return {"valid": not errors, "errors": errors, "entry_count": len(observed)}


__all__ = [
    "DEFAULT_ARCHIVE",
    "DEFAULT_EXTRA_PATHS",
    "DEFAULT_REPRODUCTION_MANIFEST",
    "DEFAULT_SIDECAR",
    "build_release_candidate",
    "verify_release_candidate",
]
