"""Failure decomposition for conjunctive mechanism qualification gates.

The analysis deliberately does not turn guardrails into a composite score.
It explains which requirements block each method and which minimum sets of
requirements would have to be relaxed before a method enters the candidate
set.  A relaxation is diagnostic, not a deployment recommendation.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .qualification import normalize_qualification_status

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOINT_ADMISSIBILITY = (
    PACKAGE_ROOT
    / "outputs"
    / "kdd_aggregate_type_envelope"
    / "joint_admissibility.csv"
)
DEFAULT_OUTPUT = PACKAGE_ROOT / "outputs" / "kdd_qualification_analysis"
ANALYSIS_ROLE = "diagnostic_not_official_rank"


@dataclass(frozen=True)
class QualificationEvidence:
    method_id: str
    requirement_status: Mapping[str, str]
    context: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MethodQualificationDecomposition:
    method_id: str
    joint_status: str
    passed_requirements: tuple[str, ...]
    failed_requirements: tuple[str, ...]
    unauditable_requirements: tuple[str, ...]
    not_required_requirements: tuple[str, ...]
    minimum_relaxation_count: int
    minimum_relaxation_requirements: tuple[str, ...]
    blocker_kinds: tuple[str, ...]
    analysis_role: str = ANALYSIS_ROLE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelaxationFrontierRow:
    relaxed_requirements: tuple[str, ...]
    relaxation_size: int
    newly_admitted_method_ids: tuple[str, ...]
    admitted_method_ids: tuple[str, ...]
    admitted_method_count: int
    analysis_role: str = ANALYSIS_ROLE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualificationAnalysis:
    methods: tuple[MethodQualificationDecomposition, ...]
    relaxation_frontier: tuple[RelaxationFrontierRow, ...]
    summary: Mapping[str, Any]


def _blocker_kind(requirement: str, status: str) -> str:
    if status == "not_auditable":
        return "evidence_missing"
    if requirement == "source_fidelity":
        return "source_fidelity_gap"
    if requirement == "finite_no_counterexample":
        return "finite_counterexample"
    return "observed_guardrail_failure"


def analyze_qualification(
    evidence: Sequence[QualificationEvidence],
) -> QualificationAnalysis:
    """Explain a conjunctive gate without assigning a cross-property rank."""

    if not evidence:
        raise ValueError("qualification analysis requires at least one method")
    method_ids = [row.method_id.strip() for row in evidence]
    if any(not method_id for method_id in method_ids) or len(set(method_ids)) != len(
        method_ids
    ):
        raise ValueError("qualification method IDs must be non-empty and unique")
    requirements = sorted(
        {str(name).strip() for row in evidence for name in row.requirement_status}
    )
    if not requirements or any(not requirement for requirement in requirements):
        raise ValueError("qualification requirements must be non-empty")

    decomposed: list[MethodQualificationDecomposition] = []
    for row in evidence:
        statuses = {
            requirement: normalize_qualification_status(
                row.requirement_status.get(requirement, "not_auditable")
            )
            for requirement in requirements
        }
        passed = tuple(name for name in requirements if statuses[name] == "pass")
        failed = tuple(name for name in requirements if statuses[name] == "fail")
        unauditable = tuple(
            name for name in requirements if statuses[name] == "not_auditable"
        )
        not_required = tuple(
            name for name in requirements if statuses[name] == "not_required"
        )
        blockers = tuple(sorted((*failed, *unauditable)))
        joint_status = "fail" if failed else "not_auditable" if unauditable else "pass"
        blocker_kinds = tuple(
            sorted(
                {
                    _blocker_kind(name, statuses[name])
                    for name in blockers
                }
            )
        )
        decomposed.append(
            MethodQualificationDecomposition(
                method_id=row.method_id,
                joint_status=joint_status,
                passed_requirements=passed,
                failed_requirements=failed,
                unauditable_requirements=unauditable,
                not_required_requirements=not_required,
                minimum_relaxation_count=len(blockers),
                minimum_relaxation_requirements=blockers,
                blocker_kinds=blocker_kinds,
            )
        )

    method_rows = tuple(sorted(decomposed, key=lambda item: item.method_id))
    unique_paths = sorted(
        {
            row.minimum_relaxation_requirements
            for row in method_rows
            if row.minimum_relaxation_requirements
        },
        key=lambda path: (len(path), path),
    )
    frontier: list[RelaxationFrontierRow] = []
    for path in unique_paths:
        relaxed = set(path)
        newly = tuple(
            row.method_id
            for row in method_rows
            if row.minimum_relaxation_requirements == path
        )
        admitted = tuple(
            row.method_id
            for row in method_rows
            if set(row.minimum_relaxation_requirements).issubset(relaxed)
        )
        frontier.append(
            RelaxationFrontierRow(
                relaxed_requirements=path,
                relaxation_size=len(path),
                newly_admitted_method_ids=newly,
                admitted_method_ids=admitted,
                admitted_method_count=len(admitted),
            )
        )
    summary = {
        "analysis_role": ANALYSIS_ROLE,
        "headline_method_count": len(method_rows),
        "joint_pass_count": sum(row.joint_status == "pass" for row in method_rows),
        "joint_fail_count": sum(row.joint_status == "fail" for row in method_rows),
        "joint_not_auditable_count": sum(
            row.joint_status == "not_auditable" for row in method_rows
        ),
        "observed_failure_method_count": sum(
            bool(row.failed_requirements) for row in method_rows
        ),
        "evidence_missing_method_count": sum(
            bool(row.unauditable_requirements) for row in method_rows
        ),
        "one_requirement_near_miss_count": sum(
            row.minimum_relaxation_count == 1 for row in method_rows
        ),
        "minimum_relaxation_path_count": len(frontier),
        "requirements": requirements,
        "claim_boundary": (
            "Observed failures are finite benchmark observations; missing evidence is "
            "not a failure; relaxations are diagnostics and not an official rank or "
            "deployment recommendation."
        ),
    }
    return QualificationAnalysis(method_rows, tuple(frontier), summary)


def _parse_bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{label} must be true or false")
    return normalized == "true"


def _load_joint_admissibility(path: Path) -> tuple[QualificationEvidence, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("joint admissibility input is empty")
    evidence: list[QualificationEvidence] = []
    for row in rows:
        method_id = str(row.get("method_id", "")).strip()
        sbb_applicable = _parse_bool(
            str(row.get("strong_budget_balance_applicable_all_profiles", "")),
            f"{method_id}.strong_budget_balance_applicable_all_profiles",
        )
        finite_conclusion = str(row.get("finite_audit_conclusion", "")).strip()
        evidence.append(
            QualificationEvidence(
                method_id=method_id,
                requirement_status={
                    "source_fidelity": (
                        "pass"
                        if _parse_bool(str(row.get("paper_exact", "")), f"{method_id}.paper_exact")
                        else "fail"
                    ),
                    "individual_rationality": (
                        "pass"
                        if _parse_bool(
                            str(row.get("individual_rationality_all_profiles", "")),
                            f"{method_id}.individual_rationality_all_profiles",
                        )
                        else "fail"
                    ),
                    "weak_budget_balance": (
                        "pass"
                        if _parse_bool(
                            str(row.get("weak_budget_balance_all_profiles", "")),
                            f"{method_id}.weak_budget_balance_all_profiles",
                        )
                        else "fail"
                    ),
                    "strong_budget_balance": (
                        "not_auditable"
                        if not sbb_applicable
                        else "pass"
                        if _parse_bool(
                            str(row.get("strong_budget_balance_all_profiles", "")),
                            f"{method_id}.strong_budget_balance_all_profiles",
                        )
                        else "fail"
                    ),
                    "finite_no_counterexample": (
                        "not_auditable"
                        if not finite_conclusion or finite_conclusion == "missing"
                        else "pass"
                        if _parse_bool(
                            str(
                                row.get(
                                    "finite_no_counterexample_on_declared_estimand",
                                    "",
                                )
                            ),
                            f"{method_id}.finite_no_counterexample",
                        )
                        else "fail"
                    ),
                },
                context={
                    "provenance_kind": row.get("provenance_kind", ""),
                    "finite_audit_conclusion": finite_conclusion,
                    "evidence_boundary": row.get("evidence_boundary", ""),
                },
            )
        )
    return tuple(evidence)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    repository_root = PACKAGE_ROOT.parent.resolve()
    try:
        return resolved.relative_to(repository_root).as_posix()
    except ValueError:
        return path.name


def _csv_text(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                column: (
                    ";".join(str(item) for item in value)
                    if isinstance((value := row.get(column, "")), tuple)
                    else value
                )
                for column in columns
            }
        )
    return stream.getvalue()


def build_qualification_analysis(
    joint_admissibility_path: str | Path = DEFAULT_JOINT_ADMISSIBILITY,
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Build deterministic diagnostic artifacts from the frozen joint gate."""

    source = Path(joint_admissibility_path)
    if not source.is_file():
        raise ValueError(f"missing joint admissibility input: {source}")
    analysis = analyze_qualification(_load_joint_admissibility(source))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    method_columns = (
        "method_id",
        "joint_status",
        "passed_requirements",
        "failed_requirements",
        "unauditable_requirements",
        "not_required_requirements",
        "minimum_relaxation_count",
        "minimum_relaxation_requirements",
        "blocker_kinds",
        "analysis_role",
    )
    frontier_columns = (
        "relaxed_requirements",
        "relaxation_size",
        "newly_admitted_method_ids",
        "admitted_method_ids",
        "admitted_method_count",
        "analysis_role",
    )
    method_path = output / "method_failure_decomposition.csv"
    frontier_path = output / "minimum_relaxation_frontier.csv"
    method_path.write_text(
        _csv_text([row.to_dict() for row in analysis.methods], method_columns),
        encoding="utf-8",
    )
    frontier_path.write_text(
        _csv_text(
            [row.to_dict() for row in analysis.relaxation_frontier],
            frontier_columns,
        ),
        encoding="utf-8",
    )
    summary = dict(analysis.summary)
    summary.update(
        {
            "schema_version": "1.0",
            "source_path": _portable_path(source),
            "source_sha256": _sha256(source),
        }
    )
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_lines = [
        "# Qualification failure decomposition",
        "",
        "This diagnostic explains the conjunctive headline gate; it is not a new leaderboard.",
        "An observed failure is kept separate from a not-auditable evidence gap.",
        "",
        f"- Headline methods: {summary['headline_method_count']}",
        f"- Full-gate passes: {summary['joint_pass_count']}",
        f"- Methods with an observed failure: {summary['observed_failure_method_count']}",
        f"- Methods with missing evidence: {summary['evidence_missing_method_count']}",
        f"- One-requirement near misses: {summary['one_requirement_near_miss_count']}",
        "",
        "| Method | Joint status | Failed | Not auditable | Minimum relaxation |",
        "|---|---|---|---|---|",
    ]
    for row in analysis.methods:
        report_lines.append(
            "| "
            + " | ".join(
                (
                    row.method_id,
                    row.joint_status,
                    ", ".join(row.failed_requirements) or "—",
                    ", ".join(row.unauditable_requirements) or "—",
                    ", ".join(row.minimum_relaxation_requirements) or "none",
                )
            )
            + " |"
        )
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary


__all__ = [
    "ANALYSIS_ROLE",
    "DEFAULT_JOINT_ADMISSIBILITY",
    "DEFAULT_OUTPUT",
    "MethodQualificationDecomposition",
    "QualificationAnalysis",
    "QualificationEvidence",
    "RelaxationFrontierRow",
    "analyze_qualification",
    "build_qualification_analysis",
]
