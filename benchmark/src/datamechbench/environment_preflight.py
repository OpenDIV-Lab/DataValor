"""Dependency-light preflight for the native Python reproduction workflow."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence

REFERENCE_PYTHON = (3, 12, 7)
MINIMUM_PYTHON = (3, 10, 0)
REFERENCE_SYSTEM = "Linux"
REFERENCE_MACHINES = frozenset({"x86_64", "amd64"})
REQUIRED_SOURCE_TREES = (
    "src/datavalor",
    "benchmark/src/datamechbench",
)
_LOCK_LINE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)")
_NORMALIZE_NAME = re.compile(r"[-_.]+")


def _normalized_name(value: str) -> str:
    return _NORMALIZE_NAME.sub("-", value).lower()


def _version_text(version: Sequence[int]) -> str:
    parts = tuple(int(part) for part in version[:3])
    return ".".join(str(part) for part in parts)


@dataclass(frozen=True)
class PackageCheck:
    name: str
    expected: str
    observed: str | None
    status: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "expected": self.expected,
            "observed": self.observed,
            "status": self.status,
        }


@dataclass(frozen=True)
class PythonEnvironmentAudit:
    lock_file: str
    lock_sha256: str
    repository_root: str
    python_version: str
    system: str
    machine: str
    packages: tuple[PackageCheck, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    runtime_kind: str = "native_python_source_library"
    container_or_vm_image_required: bool = False

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def package_counts(self) -> dict[str, int]:
        return {
            status: sum(package.status == status for package in self.packages)
            for status in ("matched", "mismatched", "missing")
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "report_kind": "native_python_environment_preflight",
            "passed": self.passed,
            "runtime_kind": self.runtime_kind,
            "container_or_vm_image_required": self.container_or_vm_image_required,
            "lock_file": self.lock_file,
            "lock_sha256": self.lock_sha256,
            "repository_root": self.repository_root,
            "python_version": self.python_version,
            "reference_python": _version_text(REFERENCE_PYTHON),
            "minimum_python": _version_text(MINIMUM_PYTHON),
            "system": self.system,
            "machine": self.machine,
            "package_counts": self.package_counts,
            "packages": [package.as_dict() for package in self.packages],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _parse_lock(contents: str, errors: list[str]) -> tuple[tuple[str, str], ...]:
    requirements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        contents.splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            errors.append(f"invalid_lock_line:{line_number}:{line}")
            continue
        name, expected = match.groups()
        normalized = _normalized_name(name)
        if normalized in seen:
            errors.append(f"duplicate_locked_package:{normalized}")
            continue
        seen.add(normalized)
        requirements.append((name, expected))
    if not requirements:
        errors.append("empty_lock_file")
    return tuple(requirements)


def audit_python_environment(
    lock_path: str | Path,
    repository_root: str | Path,
    *,
    installed_versions: Mapping[str, str] | None = None,
    python_version: Sequence[int],
    system: str,
    machine: str,
) -> PythonEnvironmentAudit:
    """Audit an exact CPU lock without importing numerical dependencies."""

    lock = Path(lock_path).resolve()
    root = Path(repository_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    observed_python = tuple(int(part) for part in python_version[:3])
    python_text = _version_text(observed_python)
    if observed_python < MINIMUM_PYTHON:
        errors.append(
            f"unsupported_python:requires>=3.10:observed={python_text}"
        )
    elif observed_python != REFERENCE_PYTHON:
        warnings.append(
            "non_reference_python:expected=3.12.7:observed=" + python_text
        )
    normalized_machine = machine.lower()
    if system != REFERENCE_SYSTEM or normalized_machine not in REFERENCE_MACHINES:
        warnings.append(f"non_reference_platform:{system}/{machine}")

    if not lock.is_file():
        errors.append(f"missing_lock_file:{lock.as_posix()}")
        requirements: tuple[tuple[str, str], ...] = ()
        lock_sha256 = ""
    else:
        try:
            lock_bytes = lock.read_bytes()
        except OSError as exc:
            errors.append(f"unreadable_lock_file:{type(exc).__name__}")
            requirements = ()
            lock_sha256 = ""
        else:
            lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
            try:
                lock_text = lock_bytes.decode("utf-8")
            except UnicodeError as exc:
                errors.append(f"unreadable_lock_file:{type(exc).__name__}")
                requirements = ()
            else:
                requirements = _parse_lock(lock_text, errors)

    for relative in REQUIRED_SOURCE_TREES:
        if not (root / relative).is_dir():
            errors.append(f"missing_source_tree:{relative}")

    provided = (
        {_normalized_name(name): str(value) for name, value in installed_versions.items()}
        if installed_versions is not None
        else None
    )
    packages: list[PackageCheck] = []
    for name, expected in requirements:
        normalized = _normalized_name(name)
        if provided is not None:
            observed = provided.get(normalized)
        else:
            try:
                observed = metadata.version(name)
            except metadata.PackageNotFoundError:
                observed = None
        if observed is None:
            status = "missing"
            errors.append(f"package_missing:{name}:expected={expected}")
        elif observed != expected:
            status = "mismatched"
            errors.append(
                f"package_version_mismatch:{name}:expected={expected}:observed={observed}"
            )
        else:
            status = "matched"
        packages.append(PackageCheck(name, expected, observed, status))

    return PythonEnvironmentAudit(
        lock_file=lock.as_posix(),
        lock_sha256=lock_sha256,
        repository_root=root.as_posix(),
        python_version=python_text,
        system=system,
        machine=machine,
        packages=tuple(packages),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


__all__ = [
    "MINIMUM_PYTHON",
    "REFERENCE_PYTHON",
    "PackageCheck",
    "PythonEnvironmentAudit",
    "audit_python_environment",
]
