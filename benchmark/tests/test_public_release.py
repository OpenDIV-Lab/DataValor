from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from datamechbench.metrics import MetricValue
from datamechbench.models import BenchmarkResult
from datamechbench.public_release import (
    DEFAULT_EXTRA_PATHS,
    _safe_member_path,
    build_release_candidate,
    verify_release_candidate,
)
from datamechbench.report import write_jsonl
from datamechbench.reproduction import scientific_result_digest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = (
    REPOSITORY_ROOT / "benchmark" / "scripts" / "build_kdd_release_candidate.py"
)
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
CPU_LOCK = REPOSITORY_ROOT / "benchmark" / "reproduction" / "requirements-cpu.lock"


def test_default_release_inputs_include_full_rerun_qualification_policy() -> None:
    released = {path.resolve() for path in DEFAULT_EXTRA_PATHS}
    assert (
        REPOSITORY_ROOT / "benchmark" / "catalog" / "qualification.yaml"
    ).resolve() in released


def test_default_release_inputs_include_installable_python_projects() -> None:
    released = {path.resolve() for path in DEFAULT_EXTRA_PATHS}

    assert (REPOSITORY_ROOT / "pyproject.toml").resolve() in released
    assert (REPOSITORY_ROOT / "benchmark" / "pyproject.toml").resolve() in released


def test_kdd_artifact_ci_runs_full_pipeline_from_extracted_candidate() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "Standalone full rerun from release candidate" in workflow
    assert "tar -xzf /tmp/kdd-release-a/candidate.tar.gz" in workflow
    assert "python -m venv /tmp/kdd-release-venv" in workflow
    assert "/tmp/kdd-release-venv/bin/python -m pip install -r" in workflow
    assert "--no-index --no-build-isolation --no-deps . ./benchmark" in workflow
    assert "/tmp/kdd-release-venv/bin/python" in workflow
    assert "benchmark/scripts/reproduce_kdd_core.py --run" in workflow
    assert "docker " not in workflow.lower()


def test_cpu_lock_pins_python_build_backend() -> None:
    requirements = set(CPU_LOCK.read_text(encoding="utf-8").splitlines())

    assert "setuptools==80.9.0" in requirements
    assert "wheel==0.45.1" in requirements


def test_member_path_validation_rejects_normalization_aliases() -> None:
    assert _safe_member_path("DataMechBench-v1/path/file.json") is True
    assert _safe_member_path("DataMechBench-v1/path//file.json") is False
    assert _safe_member_path("DataMechBench-v1/path/./file.json") is False
    assert _safe_member_path("DataMechBench-v1/path/../file.json") is False
    assert _safe_member_path("/DataMechBench-v1/file.json") is False
    assert _safe_member_path(r"DataMechBench-v1\file.json") is False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_repository(root: Path) -> Path:
    result = BenchmarkResult(
        run_id="run-a",
        track="valuation",
        method_id="method-a",
        case_id="case-a",
        seed=0,
        status="completed",
        metrics={"score": MetricValue(0.75)},
        runtime_seconds=1.0,
        metadata={"benchmark_setting": "V-TEST"},
    )
    raw = write_jsonl((result,), root / "results.jsonl")
    protocol = root / "protocol.json"
    protocol.write_text('{"frozen":true}\n', encoding="utf-8")
    source = root / "source"
    source.mkdir()
    (source / "a.py").write_text("x = 1\n", encoding="utf-8")
    source_digest = hashlib.sha256(b"a.py\0x = 1\n\0").hexdigest()
    manifest = root / "reproduction.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "manifest_kind": "kdd_core_reproduction",
                "release_id": "fixture-v1",
                "required_tracks": ["valuation"],
                "scientific_results": {
                    "path": raw.name,
                    "sha256": _sha256(raw),
                    "scientific_digest": scientific_result_digest((result,)),
                    "row_count": 1,
                    "status_counts": {"completed": 1},
                    "track_counts": {"valuation": 1},
                },
                "artifacts": [
                    {
                        "path": protocol.name,
                        "sha256": _sha256(protocol),
                        "role": "protocol",
                    }
                ],
                "source_trees": [
                    {"path": source.name, "sha256": source_digest, "file_count": 1}
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def test_release_candidate_is_byte_identical_and_normalizes_tar_metadata(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    extra = repository / "README.md"
    extra.write_text("# Fixture\n", encoding="utf-8")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    build_release_candidate(
        repository,
        reproduction,
        first / "candidate.tar.gz",
        first / "candidate.manifest.json",
        extra_paths=(extra,),
    )
    build_release_candidate(
        repository,
        reproduction,
        second / "candidate.tar.gz",
        second / "candidate.manifest.json",
        extra_paths=(extra,),
    )

    assert (first / "candidate.tar.gz").read_bytes() == (
        second / "candidate.tar.gz"
    ).read_bytes()
    assert (first / "candidate.manifest.json").read_bytes() == (
        second / "candidate.manifest.json"
    ).read_bytes()
    with tarfile.open(first / "candidate.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        assert all(member.isfile() for member in members)
        assert all(member.mtime == 0 for member in members)
        assert all(member.uid == member.gid == 0 for member in members)
        assert all(member.uname == member.gname == "" for member in members)
        assert all(member.mode == 0o644 for member in members)
        assert any(member.name.endswith("/RELEASE-METADATA.json") for member in members)
    checked = verify_release_candidate(first / "candidate.manifest.json")
    assert checked["valid"] is True
    assert checked["errors"] == []


def test_release_candidate_contains_exact_hash_bound_inputs(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"

    manifest = build_release_candidate(repository, reproduction, archive, sidecar)

    paths = [entry["path"] for entry in manifest["entries"]]
    assert paths == sorted(paths)
    assert any(path.endswith("/reproduction.json") for path in paths)
    assert any(path.endswith("/results.jsonl") for path in paths)
    assert any(path.endswith("/protocol.json") for path in paths)
    assert any(path.endswith("/source/a.py") for path in paths)
    assert manifest["archive"]["sha256"] == _sha256(archive)
    assert manifest["reproduction"]["release_id"] == "fixture-v1"
    assert manifest["entry_count"] == len(paths)


def test_post_release_evidence_does_not_change_frozen_archive(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_archive = first_dir / "candidate.tar.gz"
    first_sidecar = first_dir / "candidate.manifest.json"
    second_archive = second_dir / "candidate.tar.gz"
    second_sidecar = second_dir / "candidate.manifest.json"

    build_release_candidate(
        repository, reproduction, first_archive, first_sidecar
    )
    post_release = repository / "benchmark" / "evidence" / "post_release"
    post_release.mkdir(parents=True)
    (post_release / "kdd_release_evidence.yaml").write_text(
        "external: true\n", encoding="utf-8"
    )
    (post_release / "operator-a.json").write_text(
        '{"status":"passed"}\n', encoding="utf-8"
    )
    build_release_candidate(
        repository, reproduction, second_archive, second_sidecar
    )

    assert first_archive.read_bytes() == second_archive.read_bytes()
    assert first_sidecar.read_bytes() == second_sidecar.read_bytes()
    manifest = json.loads(second_sidecar.read_text(encoding="utf-8"))
    assert not any(
        "/benchmark/evidence/post_release/" in entry["path"]
        for entry in manifest["entries"]
    )


def test_verifier_rejects_candidate_bound_to_stale_repository_manifest(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    build_release_candidate(repository, reproduction, archive, sidecar)
    reproduction.write_text(
        reproduction.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    checked = verify_release_candidate(sidecar, repository)

    assert checked["valid"] is False
    assert checked["errors"] == [
        "repository_reproduction_manifest_sha256_mismatch:reproduction.json"
    ]


def test_verifier_rejects_internally_inconsistent_reproduction_binding(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    build_release_candidate(repository, reproduction, archive, sidecar)
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["reproduction"]["sha256"] = "0" * 64
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    checked = verify_release_candidate(sidecar)

    assert checked["valid"] is False
    assert "release_reproduction_manifest_entry_sha256_mismatch" in checked["errors"]
    assert "release_metadata_reproduction_manifest_sha256_mismatch" in checked["errors"]


def test_release_candidate_contains_replication_scientific_results(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    replication = repository / "replication_results.jsonl"
    replication.write_bytes((repository / "results.jsonl").read_bytes())
    reproduction_payload = json.loads(reproduction.read_text(encoding="utf-8"))
    primary = reproduction_payload["scientific_results"]
    reproduction_payload["replication_scientific_results"] = {
        **primary,
        "path": replication.name,
        "sha256": _sha256(replication),
    }
    reproduction.write_text(
        json.dumps(reproduction_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = build_release_candidate(
        repository,
        reproduction,
        tmp_path / "candidate.tar.gz",
        tmp_path / "candidate.manifest.json",
    )

    paths = [entry["path"] for entry in manifest["entries"]]
    assert any(path.endswith("/replication_results.jsonl") for path in paths)


def test_explicit_document_already_bound_by_reproduction_is_packaged_once(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"

    manifest = build_release_candidate(
        repository,
        reproduction,
        archive,
        sidecar,
        extra_paths=(repository / "protocol.json",),
    )

    protocol_entries = [
        entry for entry in manifest["entries"] if entry["path"].endswith("/protocol.json")
    ]
    assert len(protocol_entries) == 1


def test_verifier_detects_archive_byte_tampering(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    build_release_candidate(repository, reproduction, archive, sidecar)
    archive.write_bytes(archive.read_bytes() + b"tampered")

    checked = verify_release_candidate(sidecar)

    assert checked["valid"] is False
    assert checked["errors"] == ["archive_sha256_mismatch"]


def test_verifier_rejects_unsafe_member_even_when_archive_hash_is_rebound(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    build_release_candidate(repository, reproduction, archive, sidecar)
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                payload = b"escape"
                info = tarfile.TarInfo("../escape.txt")
                info.size = len(payload)
                info.mtime = 0
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(payload))
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    manifest["archive"]["sha256"] = _sha256(archive)
    manifest["archive"]["bytes"] = archive.stat().st_size
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")

    checked = verify_release_candidate(sidecar)

    assert checked["valid"] is False
    assert "unsafe_member_path:../escape.txt" in checked["errors"]


def test_verifier_detects_member_content_change_after_outer_hash_rebinding(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reproduction = _fixture_repository(repository)
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    build_release_candidate(repository, reproduction, archive, sidecar)
    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    target = next(entry["path"] for entry in manifest["entries"] if entry["path"].endswith("/protocol.json"))
    with tarfile.open(archive, "r:gz") as source:
        payloads = {
            member.name: source.extractfile(member).read()
            for member in source.getmembers()
            if member.isfile()
        }
    payloads[target] = b'{"frozen":false}\n'
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name, payload in sorted(payloads.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    info.mtime = 0
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(payload))
    manifest["archive"]["sha256"] = _sha256(archive)
    manifest["archive"]["bytes"] = archive.stat().st_size
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")

    checked = verify_release_candidate(sidecar)

    assert checked["valid"] is False
    assert f"member_sha256_mismatch:{target}" in checked["errors"]


def test_release_cli_builds_and_verifies_the_repository_candidate(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "candidate.tar.gz"
    sidecar = tmp_path / "candidate.manifest.json"
    environment = {
        **os.environ,
        "PYTHONPATH": str(REPOSITORY_ROOT / "benchmark" / "src"),
    }
    common = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--repository-root",
        str(REPOSITORY_ROOT),
        "--archive",
        str(archive),
        "--sidecar",
        str(sidecar),
    ]

    built = subprocess.run(
        [*common, "--build"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [*common, "--verify"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert built.returncode == 0, built.stderr
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["valid"] is True

    manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    released_paths = {entry["path"] for entry in manifest["entries"]}
    assert any(
        path.endswith("/benchmark/catalog/qualification.yaml")
        for path in released_paths
    ), "the standalone full-rerun pipeline loads the qualification policy"
    for relative in (
        "benchmark/catalog/benchmark_release.yaml",
        "benchmark/submission_template/submission.yaml",
        "benchmark/submission_template/results.jsonl",
        "benchmark/case_submission_template/case_submission.yaml",
        "benchmark/case_submission_template/source_snapshot.json",
        "benchmark/case_submission_template/transform_case.py",
    ):
        assert any(path.endswith(f"/{relative}") for path in released_paths), relative

    extracted = tmp_path / "extracted"
    with tarfile.open(archive, "r:gz") as release_archive:
        release_archive.extractall(extracted, filter="data")
    release_root = next(extracted.iterdir())
    validation = subprocess.run(
        [
            sys.executable,
            "-m",
            "datamechbench.cli",
            "validate-submission",
            "--submission",
            "benchmark/submission_template",
            "--output",
            str(tmp_path / "submission-validation.json"),
        ],
        cwd=release_root,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(("benchmark/src", "src")),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert validation.returncode == 0, validation.stderr
    assert json.loads(validation.stdout)["valid"] is True

    case_validation = subprocess.run(
        [
            sys.executable,
            "-m",
            "datamechbench.cli",
            "validate-case-submission",
            "--submission",
            "benchmark/case_submission_template",
            "--output",
            str(tmp_path / "case-submission-validation.json"),
        ],
        cwd=release_root,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(("benchmark/src", "src")),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert case_validation.returncode == 0, case_validation.stderr
    case_payload = json.loads(case_validation.stdout)
    assert case_payload["valid"] is True
    assert case_payload["review_eligible"] is False

    assert not any(
        "scr_shapley" in path.lower() or "www2027" in path.lower()
        for path in released_paths
    )
