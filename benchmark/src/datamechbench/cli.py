"""Command-line entry point for DataMechBench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .case_submission import validate_case_submission
from .elr_analysis import analyze_elr_results
from .elr_evidence_report import write_elr_evidence_report
from .reference_evaluation import write_reference_outcome_audit
from .release import write_release_artifacts
from .report import (
    load_jsonl_results,
    write_jsonl,
    write_leaderboard_csvs,
    write_markdown_report,
    write_research_artifacts,
    write_track_csvs,
)
from .runner import build_cases, load_config, run_benchmark
from .submission import evaluate_submission, validate_submission


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datamechbench")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a configured mechanism benchmark")
    run.add_argument("--config", required=True, help="YAML benchmark config")
    submission = commands.add_parser(
        "validate-submission", help="validate a result package without executing code"
    )
    submission.add_argument("--submission", required=True, help="submission directory")
    submission.add_argument(
        "--output",
        help="optional validation JSON path (defaults inside submission directory)",
    )
    evaluate = commands.add_parser(
        "evaluate-submission",
        help="validate raw outcomes and recompute authoritative metrics",
    )
    evaluate.add_argument("--submission", required=True, help="submission directory")
    evaluate.add_argument("--output", required=True, help="trusted evaluation JSON")
    case_submission = commands.add_parser(
        "validate-case-submission",
        help="validate an open-development case package without executing code",
    )
    case_submission.add_argument(
        "--submission", required=True, help="case submission directory"
    )
    case_submission.add_argument(
        "--output",
        help="optional validation JSON path (defaults inside submission directory)",
    )
    render = commands.add_parser(
        "render", help="regenerate reports from an existing raw_results.jsonl"
    )
    render.add_argument("--results", required=True, help="raw result JSONL")
    render.add_argument("--output", required=True, help="artifact output directory")
    render.add_argument("--config", help="optional original YAML run config")
    validate = commands.add_parser("validate", help="validate ELR raw-result invariants")
    validate.add_argument("--results", required=True, help="raw result JSONL")
    summarize = commands.add_parser("summarize", help="summarize ELR raw results")
    summarize.add_argument("--results", required=True, help="raw result JSONL")
    summarize.add_argument("--output", required=True, help="artifact output directory")
    summarize.add_argument("--bootstrap-samples", type=int, default=10_000)
    evidence = commands.add_parser(
        "evidence-report", help="generate the pre-registered ELR evidence report"
    )
    evidence.add_argument("--results", required=True, help="raw result JSONL")
    evidence.add_argument("--output", required=True, help="artifact output directory")
    evidence.add_argument("--bootstrap-samples", type=int, default=10_000)
    reference = commands.add_parser(
        "audit-reference-outcomes",
        help="recompute standard metrics from persisted reference outcomes",
    )
    reference.add_argument("--results", required=True, help="raw result JSONL")
    reference.add_argument("--output", required=True, help="audit JSON path")
    return parser


def _elr_declarations(results) -> tuple[tuple[str, ...], tuple[float, ...]]:
    primary = [row for row in results if row.metadata.get("primary_task", False)]
    cells = tuple(
        sorted({str(row.metadata.get("setting_id", row.case_id)) for row in primary})
    )
    budgets = tuple(sorted({float(row.metadata.get("budget", 0.0)) for row in primary}))
    return cells, budgets


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        config = load_config(args.config)
        results = run_benchmark(config)
        output = Path(config.output_dir)
        write_jsonl(results, output / "raw_results.jsonl")
        write_track_csvs(results, output)
        write_leaderboard_csvs(results, output)
        write_research_artifacts(results, output, config_path=args.config)
        write_markdown_report(results, output / "report.md")
        write_release_artifacts(results, output, config_path=args.config)
        return 0
    if args.command == "validate-submission":
        validation = validate_submission(args.submission)
        payload = validation.to_dict()
        target = (
            Path(args.output)
            if args.output
            else Path(args.submission) / "submission_validation.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if validation.valid else 1
    if args.command == "evaluate-submission":
        payload = evaluate_submission(args.submission)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["validation"]["valid"] else 1
    if args.command == "validate-case-submission":
        validation = validate_case_submission(args.submission)
        payload = validation.to_dict()
        target = (
            Path(args.output)
            if args.output
            else Path(args.submission) / "case_submission_validation.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if validation.valid else 1
    if args.command == "render":
        results = load_jsonl_results(args.results)
        output = Path(args.output)
        write_track_csvs(results, output)
        write_leaderboard_csvs(results, output)
        write_research_artifacts(results, output, config_path=args.config)
        write_markdown_report(results, output / "report.md")
        write_release_artifacts(results, output, config_path=args.config)
        return 0
    if args.command == "audit-reference-outcomes":
        output = write_reference_outcome_audit(
            args.results, args.output, cases=build_cases()
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["passed"] else 1
    if args.command == "validate":
        results = load_jsonl_results(args.results)
        run_ids = [row.run_id for row in results]
        cells, budgets = _elr_declarations(results)
        errors = []
        if len(run_ids) != len(set(run_ids)):
            errors.append("duplicate_run_ids")
        if not results:
            errors.append("empty_results")
        if not cells or not budgets:
            errors.append("missing_primary_declarations")
        payload = {
            "valid": not errors,
            "errors": errors,
            "result_count": len(results),
            "declared_cells": cells,
            "declared_budgets": budgets,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not errors else 1
    if args.command in {"summarize", "evidence-report"}:
        results = load_jsonl_results(args.results)
        cells, budgets = _elr_declarations(results)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        if args.command == "summarize":
            analysis = analyze_elr_results(
                results,
                declared_cells=cells,
                declared_budgets=budgets,
                bootstrap_samples=args.bootstrap_samples,
            )
            (output / "elr_summary.json").write_text(
                json.dumps(analysis.to_dict(), indent=2, sort_keys=True) + "\n"
            )
        else:
            write_elr_evidence_report(
                results,
                output,
                declared_cells=cells,
                declared_budgets=budgets,
                bootstrap_samples=args.bootstrap_samples,
            )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
