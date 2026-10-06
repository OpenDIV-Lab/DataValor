#!/usr/bin/env python3
"""Run or verify the frozen KDD 2027 CPU core without self-certifying it."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from datamechbench.reproduction import (
    create_clean_room_record,
    load_reproduction_manifest,
    verify_reproduction_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = "benchmark/reproduction/kdd2027_core_manifest.json"
HELDOUT_RUNNER = "benchmark/scripts/run_kdd_heldout_confirmation.py"
REPLICATION_REPORT_RUNNER = "benchmark/scripts/build_kdd_replication_report.py"
FINITE_INCENTIVE_RUNNER = "benchmark/scripts/run_kdd_finite_incentives.py"
TRADING_GEOMETRY_RUNNER = "benchmark/scripts/run_trading_geometry_study.py"
AGGREGATE_TYPE_ENVELOPE_RUNNER = (
    "benchmark/scripts/run_aggregate_type_envelope.py"
)
DIRECT_MARKET_CALIBRATION_RUNNER = (
    "benchmark/scripts/build_dadada_market_calibration.py"
)
DIRECT_MARKET_TRANSFER_RUNNER = "benchmark/scripts/run_direct_market_transfer.py"
EXTERNAL_SHAPLEY_RUNNER = "benchmark/scripts/run_external_shapley_validation.py"
EXTERNAL_MCAFEE_RUNNER = "benchmark/scripts/run_external_mcafee_validation.py"
EXTERNAL_SBBA_RUNNER = "benchmark/scripts/run_external_sbba_validation.py"
TRIPLE_EAGLE_RUNNER = "benchmark/scripts/run_triple_eagle_extension.py"
BFM_VM_RUNNER = "benchmark/scripts/run_bfm_vm_extension.py"
PAPER_ARTIFACT_RUNNER = "benchmark/scripts/build_kdd_paper_artifacts.py"
DECISION_IMPACT_RUNNER = "benchmark/scripts/build_decision_impact.py"
MECHANISM_RISK_RUNNER = "benchmark/scripts/build_mechanism_risk_cards.py"
MARKET_SEMANTICS_RUNNER = "benchmark/scripts/build_market_semantic_alignment.py"
QUALIFICATION_ANALYSIS_RUNNER = (
    "benchmark/scripts/build_qualification_analysis.py"
)
RUN_STAGES = (
    ("heldout", HELDOUT_RUNNER, ()),
    (
        "heldout_replication_v2",
        HELDOUT_RUNNER,
        (
            "--config", "benchmark/configs/kdd_heldout_replication_v2.yaml",
            "--protocol", "benchmark/evidence/kdd_heldout_replication_protocol_v1.json",
            "--output", "benchmark/outputs/kdd_heldout_replication_v2",
            "--manifest", "benchmark/evidence/kdd_heldout_replication_v2.json",
            "--data-root", "benchmark/data/replication_v2",
            "--run-name", "datamechbench-kdd-heldout-replication-v2",
        ),
    ),
    ("replication_report", REPLICATION_REPORT_RUNNER, ()),
    ("finite_incentive", FINITE_INCENTIVE_RUNNER, ()),
    ("trading_geometry", TRADING_GEOMETRY_RUNNER, ("--build",)),
    (
        "aggregate_type_envelope",
        AGGREGATE_TYPE_ENVELOPE_RUNNER,
        ("--build",),
    ),
    (
        "direct_market_calibration",
        DIRECT_MARKET_CALIBRATION_RUNNER,
        ("--verify",),
    ),
    ("direct_market_transfer", DIRECT_MARKET_TRANSFER_RUNNER, ("--build",)),
    ("external_shapley", EXTERNAL_SHAPLEY_RUNNER, ("--build",)),
    ("external_mcafee", EXTERNAL_MCAFEE_RUNNER, ("--build",)),
    ("external_sbba", EXTERNAL_SBBA_RUNNER, ("--build",)),
    ("triple_eagle_extension", TRIPLE_EAGLE_RUNNER, ("--build",)),
    ("bfm_vm_extension", BFM_VM_RUNNER, ("--build",)),
    ("market_semantics", MARKET_SEMANTICS_RUNNER, ()),
    ("qualification_analysis", QUALIFICATION_ANALYSIS_RUNNER, ()),
    ("paper_artifact", PAPER_ARTIFACT_RUNNER, ()),
    ("decision_impact", DECISION_IMPACT_RUNNER, ("--build",)),
    ("mechanism_risk", MECHANISM_RISK_RUNNER, ("--build",)),
)


def _runtime_pythonpath(root: Path, existing: str = "") -> str:
    """Return the explicit source path needed by both benchmark packages."""

    entries = [str(root / "benchmark" / "src"), str(root / "src")]
    if existing:
        entries.append(existing)
    return os.pathsep.join(entries)


def _runtime_version_error(version: Sequence[int]) -> str | None:
    """Return a stable diagnostic when the supported Python floor is unmet."""

    observed = tuple(int(part) for part in version[:3])
    if observed[:2] >= (3, 10):
        return None
    rendered = ".".join(str(part) for part in observed)
    return f"unsupported_python:requires>=3.10:observed={rendered}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproduce or verify the frozen DataMechBench KDD core."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--repository-root", default=str(REPOSITORY_ROOT))
    parser.add_argument("--report", required=True)
    parser.add_argument("--operator-record")
    parser.add_argument("--operator-id")
    parser.add_argument("--isolation", choices=("fresh_venv",))
    parser.add_argument("--setup-minutes", type=float)
    parser.add_argument("--source-archive-url")
    parser.add_argument("--source-archive-sha256")
    parser.add_argument("--environment-preflight", type=Path)
    parser.add_argument(
        "--attest-independent-of-implementation", action="store_true"
    )
    parser.add_argument("--attest-no-source-modifications", action="store_true")
    parser.add_argument(
        "--attest-no-unexpected-differences", action="store_true"
    )
    parser.add_argument("--unexpected-difference", action="append", default=[])
    return parser


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _public_replay_command(raw_argv: Sequence[str], root: Path) -> str:
    """Render a replayable command without publishing operator-local paths."""

    normalized: list[str] = []
    for token in raw_argv:
        candidate = Path(token)
        if not candidate.is_absolute():
            normalized.append(token)
            continue
        try:
            relative = candidate.resolve().relative_to(root)
        except ValueError:
            normalized.append(candidate.name)
        else:
            normalized.append(relative.as_posix() if relative.parts else ".")
    return shlex.join(
        ["python", "benchmark/scripts/reproduce_kdd_core.py", *normalized]
    )


def _run_pipeline(
    root: Path,
    environment: dict[str, str],
    *,
    runner=subprocess.run,
) -> str | None:
    """Run each scientific build stage in dependency order and fail at first error."""

    for label, relative_path, arguments in RUN_STAGES:
        completed = runner(
            [sys.executable, str(root / relative_path), *arguments],
            cwd=root,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            return f"{label}_runner_exit_code:{completed.returncode}"
    return None


def _write_operator_record(
    args: argparse.Namespace,
    raw_argv: Sequence[str],
    root: Path,
    payload: dict[str, object],
    *,
    exit_code: int,
) -> None:
    if not args.operator_record:
        return
    fully_confirmed = (
        args.attest_independent_of_implementation
        and args.attest_no_source_modifications
        and args.attest_no_unexpected_differences
    )
    differences = list(args.unexpected_difference)
    if not args.attest_no_unexpected_differences and not differences:
        differences = ["<absence of unexpected differences not attested>"]
    command = _public_replay_command(raw_argv, root)
    record = create_clean_room_record(
        args.manifest,
        root,
        operator_id=args.operator_id,
        independent_of_implementation=args.attest_independent_of_implementation,
        isolation=args.isolation,
        os_description=platform.platform(),
        python_version=platform.python_version(),
        command=command,
        exit_code=exit_code,
        setup_minutes=args.setup_minutes,
        artifact_verification_passed=payload.get("passed") is True,
        observed_scientific_digest=payload.get("scientific_digest"),
        operator_confirmed=fully_confirmed,
        no_source_modifications=args.attest_no_source_modifications,
        unexpected_differences=differences,
        source_archive_url=args.source_archive_url,
        source_archive_sha256=args.source_archive_sha256,
        environment_preflight=args.environment_preflight_payload,
    )
    _write_report(Path(args.operator_record), record)


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    parser = _parser()
    args = parser.parse_args(raw_argv)
    if args.operator_record:
        if not args.run:
            parser.error("--operator-record requires --run")
        missing = [
            name
            for name, value in (
                ("--operator-id", args.operator_id),
                ("--isolation", args.isolation),
                ("--setup-minutes", args.setup_minutes),
                ("--source-archive-url", args.source_archive_url),
                ("--source-archive-sha256", args.source_archive_sha256),
                ("--environment-preflight", args.environment_preflight),
            )
            if value is None
        ]
        if missing:
            parser.error("--operator-record requires " + ", ".join(missing))
        if args.attest_no_unexpected_differences and args.unexpected_difference:
            parser.error(
                "--attest-no-unexpected-differences conflicts with "
                "--unexpected-difference"
            )
        try:
            args.environment_preflight_payload = json.loads(
                args.environment_preflight.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"invalid --environment-preflight: {exc}")
        if not isinstance(args.environment_preflight_payload, dict):
            parser.error("invalid --environment-preflight: expected a JSON object")
    root = Path(args.repository_root).resolve()
    report_path = Path(args.report)
    mode = "run" if args.run else "verify_only"
    base_report: dict[str, object] = {
        "schema_version": "1.0",
        "report_kind": "kdd_core_reproduction_verification",
        "mode": mode,
        "evidence_class": "internal_artifact_verification",
        "independent_reproduction": False,
        "manifest": args.manifest,
    }
    version_error = _runtime_version_error(sys.version_info)
    if version_error is not None:
        payload = {**base_report, "passed": False, "errors": [version_error]}
        _write_report(report_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    if args.run:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = _runtime_pythonpath(
            root, environment.get("PYTHONPATH", "")
        )
        pipeline_error = _run_pipeline(root, environment)
        if pipeline_error is not None:
            payload = {
                **base_report,
                "passed": False,
                "errors": [pipeline_error],
            }
            _write_report(report_path, payload)
            _write_operator_record(args, raw_argv, root, payload, exit_code=1)
            return 1

    try:
        manifest_path = root / args.manifest
        manifest = load_reproduction_manifest(manifest_path, root)
        verification = verify_reproduction_manifest(
            manifest,
            root,
            verification_mode="reproduction" if args.run else "archive",
        )
        payload = {
            **base_report,
            "passed": verification.passed,
            "errors": list(verification.errors),
            "release_id": manifest.release_id,
            "verified_artifacts": verification.verified_artifacts,
            "scientific_digest": verification.scientific_digest,
            "row_count": verification.row_count,
            "status_counts": dict(verification.status_counts),
            "track_counts": dict(verification.track_counts),
            "non_scientific_differences": list(
                verification.non_scientific_differences
            ),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            **base_report,
            "passed": False,
            "errors": [f"invalid_reproduction_manifest:{exc}"],
        }
    _write_report(report_path, payload)
    _write_operator_record(
        args,
        raw_argv,
        root,
        payload,
        exit_code=0 if payload["passed"] else 1,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
