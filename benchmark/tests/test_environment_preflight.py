from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _preflight_module():
    try:
        from datamechbench import environment_preflight
    except ImportError as exc:  # pragma: no cover - exercised in the TDD red run
        pytest.fail(f"environment preflight module is missing: {exc}")
    return environment_preflight


def _source_root(tmp_path: Path) -> Path:
    (tmp_path / "src" / "datavalor").mkdir(parents=True)
    (tmp_path / "benchmark" / "src" / "datamechbench").mkdir(parents=True)
    return tmp_path


def test_exact_locked_native_python_environment_passes(tmp_path: Path) -> None:
    module = _preflight_module()
    root = _source_root(tmp_path)
    lock = tmp_path / "requirements.lock"
    lock.write_text("numpy==2.3.5\nPyYAML==6.0.2\n", encoding="utf-8")

    audit = module.audit_python_environment(
        lock,
        root,
        installed_versions={"numpy": "2.3.5", "pyyaml": "6.0.2"},
        python_version=(3, 12, 7),
        system="Linux",
        machine="x86_64",
    )

    assert audit.passed is True
    assert audit.errors == ()
    assert audit.warnings == ()
    assert audit.package_counts == {"matched": 2, "mismatched": 0, "missing": 0}
    assert audit.runtime_kind == "native_python_source_library"
    assert audit.container_or_vm_image_required is False


def test_preflight_fails_closed_on_runtime_lock_and_source_errors(
    tmp_path: Path,
) -> None:
    module = _preflight_module()
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "numpy==2.3.5\nscipy==1.15.3\ninvalid>=1\n",
        encoding="utf-8",
    )

    audit = module.audit_python_environment(
        lock,
        tmp_path,
        installed_versions={"numpy": "2.2.6"},
        python_version=(3, 9, 18),
        system="Darwin",
        machine="arm64",
    )

    assert audit.passed is False
    assert "unsupported_python:requires>=3.10:observed=3.9.18" in audit.errors
    assert "invalid_lock_line:3:invalid>=1" in audit.errors
    assert "package_version_mismatch:numpy:expected=2.3.5:observed=2.2.6" in audit.errors
    assert "package_missing:scipy:expected=1.15.3" in audit.errors
    assert "missing_source_tree:src/datavalor" in audit.errors
    assert "missing_source_tree:benchmark/src/datamechbench" in audit.errors
    assert "non_reference_platform:Darwin/arm64" in audit.warnings
    assert audit.package_counts == {"matched": 0, "mismatched": 1, "missing": 1}


def test_supported_nonreference_python_is_an_explicit_warning(tmp_path: Path) -> None:
    module = _preflight_module()
    root = _source_root(tmp_path)
    lock = tmp_path / "requirements.lock"
    lock.write_text("PyYAML==6.0.2\n", encoding="utf-8")

    audit = module.audit_python_environment(
        lock,
        root,
        installed_versions={"pyyaml": "6.0.2"},
        python_version=(3, 13, 5),
        system="Linux",
        machine="x86_64",
    )

    assert audit.passed is True
    assert audit.errors == ()
    assert audit.warnings == (
        "non_reference_python:expected=3.12.7:observed=3.13.5",
    )


def test_unreadable_lock_is_reported_without_importing_dependencies(
    tmp_path: Path,
) -> None:
    module = _preflight_module()
    root = _source_root(tmp_path)
    lock = tmp_path / "requirements.lock"
    lock.write_bytes(b"\xff")

    audit = module.audit_python_environment(
        lock,
        root,
        installed_versions={},
        python_version=(3, 12, 7),
        system="Linux",
        machine="x86_64",
    )

    assert audit.passed is False
    assert audit.errors == ("unreadable_lock_file:UnicodeDecodeError",)
    assert audit.packages == ()


def test_native_python_preflight_cli_writes_machine_readable_report(
    tmp_path: Path,
) -> None:
    root = _source_root(tmp_path / "release")
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"PyYAML=={version('PyYAML')}\n", encoding="utf-8")
    output = tmp_path / "preflight.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "benchmark" / "src")

    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "benchmark" / "scripts" / "check_kdd_environment.py"),
            "--lock",
            str(lock),
            "--repository-root",
            str(root),
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    stdout = json.loads(completed.stdout)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert stdout == report
    assert report["passed"] is True
    assert report["runtime_kind"] == "native_python_source_library"
    assert report["container_or_vm_image_required"] is False
    assert report["package_counts"] == {
        "matched": 1,
        "mismatched": 0,
        "missing": 0,
    }
