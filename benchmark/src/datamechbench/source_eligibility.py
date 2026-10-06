"""Fail-closed admission audit for direct data-market calibration sources."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
REQUIRED_SOURCE_CRITERIA = (
    "institution_semantics",
    "roles_and_rights",
    "price_semantics",
    "reproducible_access",
    "reuse_rights",
    "privacy_safe",
    "independent_units",
    "transformation_audit",
)
_ALLOWED_CRITERION_STATUSES = frozenset({"met", "not_met", "unknown"})
_ALLOWED_ADMISSION_STATUSES = frozenset({"eligible", "ineligible", "pending"})


@dataclass(frozen=True)
class SourceCandidateDecision:
    candidate_id: str
    name: str
    declared_status: str
    derived_status: str
    eligible: bool
    blocking_criteria: tuple[str, ...]
    criterion_statuses: Mapping[str, str]
    evidence_unit: str
    allowed_uses: tuple[str, ...]
    prohibited_uses: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "declared_status": self.declared_status,
            "derived_status": self.derived_status,
            "eligible": self.eligible,
            "blocking_criteria": list(self.blocking_criteria),
            "criterion_statuses": dict(self.criterion_statuses),
            "admission_scope": {
                "evidence_unit": self.evidence_unit,
                "allowed_uses": list(self.allowed_uses),
                "prohibited_uses": list(self.prohibited_uses),
            },
        }


@dataclass(frozen=True)
class SourceCandidateAudit:
    catalog: str
    schema_version: str
    audit_date: str
    candidate_count: int
    decisions: tuple[SourceCandidateDecision, ...]
    eligible_candidate_ids: tuple[str, ...]
    ineligible_candidate_ids: tuple[str, ...]
    pending_candidate_ids: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        criterion_summary: dict[str, dict[str, int]] = {}
        for criterion in REQUIRED_SOURCE_CRITERIA:
            counts = Counter(
                decision.criterion_statuses[criterion]
                for decision in self.decisions
            )
            criterion_summary[criterion] = {
                "met": counts["met"],
                "not_met": counts["not_met"],
                "unknown": counts["unknown"],
                "blocking_count": counts["not_met"] + counts["unknown"],
            }

        release_trio = (
            "reproducible_access",
            "reuse_rights",
            "privacy_safe",
        )

        def all_met(
            decision: SourceCandidateDecision, criteria: tuple[str, ...]
        ) -> bool:
            return all(
                decision.criterion_statuses[criterion] == "met"
                for criterion in criteria
            )

        semantic_pair = ("institution_semantics", "price_semantics")
        blocker_distribution = Counter(
            len(decision.blocking_criteria) for decision in self.decisions
        )
        return {
            "report_kind": "direct_market_source_candidate_audit",
            "schema_version": self.schema_version,
            "audit_date": self.audit_date,
            "catalog": self.catalog,
            "valid": self.valid,
            "candidate_count": self.candidate_count,
            "eligible_candidate_count": len(self.eligible_candidate_ids),
            "ineligible_candidate_count": len(self.ineligible_candidate_ids),
            "pending_candidate_count": len(self.pending_candidate_ids),
            "eligible_candidate_ids": list(self.eligible_candidate_ids),
            "ineligible_candidate_ids": list(self.ineligible_candidate_ids),
            "pending_candidate_ids": list(self.pending_candidate_ids),
            "errors": list(self.errors),
            "criterion_summary": criterion_summary,
            "admission_funnel": {
                "candidate_count": self.candidate_count,
                "institution_and_price_semantics_met_count": sum(
                    all_met(decision, semantic_pair) for decision in self.decisions
                ),
                "release_trio_met_count": sum(
                    all_met(decision, release_trio) for decision in self.decisions
                ),
                "semantics_and_release_trio_met_count": sum(
                    all_met(decision, semantic_pair + release_trio)
                    for decision in self.decisions
                ),
                "fully_eligible_count": len(self.eligible_candidate_ids),
                "release_trio_criteria": list(release_trio),
                "interpretation_scope": (
                    "audited_candidate_set_not_literature_prevalence"
                ),
            },
            "blocking_criterion_count_distribution": {
                str(count): blocker_distribution[count]
                for count in sorted(blocker_distribution)
            },
            "decisions": [decision.as_dict() for decision in self.decisions],
        }


def _mapping(raw: Any, label: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        errors.append(f"{label}:must_be_mapping")
        return {}
    return raw


def _required_text(
    record: Mapping[str, Any], field: str, prefix: str, errors: list[str]
) -> str:
    value = str(record.get(field, "")).strip()
    if not value or value.startswith("<"):
        errors.append(f"{prefix}:missing_{field}")
    return value


def _derived_status(statuses: Mapping[str, str]) -> str:
    if any(status == "not_met" for status in statuses.values()):
        return "ineligible"
    if any(status != "met" for status in statuses.values()):
        return "pending"
    return "eligible"


def _catalog_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _scope_items(
    scope: Mapping[str, Any], field: str, prefix: str, errors: list[str]
) -> tuple[str, ...]:
    raw = scope.get(field)
    if not isinstance(raw, list) or not raw:
        errors.append(f"{prefix}:admission_scope:{field}:must_be_nonempty_list")
        return ()
    values = tuple(str(value).strip() for value in raw)
    if any(not value or value.startswith("<") for value in values):
        errors.append(f"{prefix}:admission_scope:{field}:invalid_item")
    if len(set(values)) != len(values):
        errors.append(f"{prefix}:admission_scope:{field}:duplicate_item")
    return values


def audit_source_candidate_catalog(path: str | Path) -> SourceCandidateAudit:
    """Audit one source ledger without treating unknown evidence as admission."""

    catalog_path = Path(path)
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("source candidate catalog must be a mapping")

    errors: list[str] = []
    schema_version = str(payload.get("schema_version", "")).strip()
    audit_date = str(payload.get("audit_date", "")).strip()
    if schema_version != "1.0":
        errors.append("unsupported_schema_version")
    if not audit_date:
        errors.append("missing_audit_date")

    declared_criteria = payload.get("eligibility_criteria")
    if not isinstance(declared_criteria, list) or tuple(declared_criteria) != (
        REQUIRED_SOURCE_CRITERIA
    ):
        errors.append("eligibility_criteria_mismatch")

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        errors.append("candidates:must_be_nonempty_list")
        raw_candidates = []

    decisions: list[SourceCandidateDecision] = []
    seen_ids: set[str] = set()
    for index, raw_candidate in enumerate(raw_candidates):
        candidate = _mapping(raw_candidate, f"candidate:{index}", errors)
        candidate_id = _required_text(candidate, "candidate_id", f"candidate:{index}", errors)
        prefix = f"candidate:{candidate_id or index}"
        if candidate_id in seen_ids:
            errors.append(f"{prefix}:duplicate_candidate_id")
        seen_ids.add(candidate_id)
        name = _required_text(candidate, "name", prefix, errors)
        source_url = _required_text(candidate, "source_url", prefix, errors)
        if source_url and not source_url.startswith(("https://", "http://")):
            errors.append(f"{prefix}:invalid_source_url")
        for field in (
            "source_kind",
            "observable",
            "proposed_use",
            "proposed_inference_unit",
        ):
            _required_text(candidate, field, prefix, errors)

        declared_status = str(candidate.get("declared_status", "")).strip()
        if declared_status not in _ALLOWED_ADMISSION_STATUSES:
            errors.append(f"{prefix}:invalid_declared_status:{declared_status}")

        criteria = _mapping(candidate.get("criteria"), f"{prefix}:criteria", errors)
        criterion_names = {str(name) for name in criteria}
        required_names = set(REQUIRED_SOURCE_CRITERIA)
        for missing in sorted(required_names - criterion_names):
            errors.append(f"{prefix}:missing_criterion:{missing}")
        for extra in sorted(criterion_names - required_names):
            errors.append(f"{prefix}:unknown_criterion:{extra}")

        statuses: dict[str, str] = {}
        for criterion in REQUIRED_SOURCE_CRITERIA:
            record = _mapping(
                criteria.get(criterion), f"{prefix}:criterion:{criterion}", errors
            )
            status = str(record.get("status", "")).strip()
            if status not in _ALLOWED_CRITERION_STATUSES:
                errors.append(f"{prefix}:criterion:{criterion}:invalid_status:{status}")
                status = "unknown"
            statuses[criterion] = status
            _required_text(record, "evidence", f"{prefix}:criterion:{criterion}", errors)
            _required_text(record, "limitation", f"{prefix}:criterion:{criterion}", errors)

        derived_status = _derived_status(statuses)
        if declared_status != derived_status:
            errors.append(
                f"{prefix}:declared_status_mismatch:"
                f"declared={declared_status}:derived={derived_status}"
            )
        evidence_unit = ""
        allowed_uses: tuple[str, ...] = ()
        prohibited_uses: tuple[str, ...] = ()
        scope_valid = True
        if derived_status == "eligible":
            raw_scope = candidate.get("admission_scope")
            if not isinstance(raw_scope, Mapping):
                errors.append(f"{prefix}:eligible_source_missing_admission_scope")
                scope_valid = False
            else:
                evidence_unit = _required_text(
                    raw_scope, "evidence_unit", f"{prefix}:admission_scope", errors
                )
                allowed_uses = _scope_items(
                    raw_scope, "allowed_uses", prefix, errors
                )
                prohibited_uses = _scope_items(
                    raw_scope, "prohibited_uses", prefix, errors
                )
                if not evidence_unit or not allowed_uses or not prohibited_uses:
                    scope_valid = False
                overlap = sorted(set(allowed_uses) & set(prohibited_uses))
                if overlap:
                    errors.append(
                        f"{prefix}:admission_scope:allowed_prohibited_overlap:"
                        + ",".join(overlap)
                    )
                    scope_valid = False
        decisions.append(
            SourceCandidateDecision(
                candidate_id=candidate_id,
                name=name,
                declared_status=declared_status,
                derived_status=derived_status,
                eligible=(
                    derived_status == "eligible"
                    and declared_status == "eligible"
                    and scope_valid
                ),
                blocking_criteria=tuple(
                    criterion
                    for criterion in REQUIRED_SOURCE_CRITERIA
                    if statuses[criterion] != "met"
                ),
                criterion_statuses=statuses,
                evidence_unit=evidence_unit,
                allowed_uses=allowed_uses,
                prohibited_uses=prohibited_uses,
            )
        )

    decisions.sort(key=lambda decision: decision.candidate_id)
    eligible = tuple(row.candidate_id for row in decisions if row.eligible)
    ineligible = tuple(
        row.candidate_id for row in decisions if row.derived_status == "ineligible"
    )
    pending = tuple(
        row.candidate_id for row in decisions if row.derived_status == "pending"
    )
    return SourceCandidateAudit(
        catalog=_catalog_label(catalog_path),
        schema_version=schema_version,
        audit_date=audit_date,
        candidate_count=len(decisions),
        decisions=tuple(decisions),
        eligible_candidate_ids=eligible,
        ineligible_candidate_ids=ineligible,
        pending_candidate_ids=pending,
        errors=tuple(errors),
    )


def write_source_candidate_audit(
    catalog_path: str | Path, output_path: str | Path
) -> Path:
    """Write a deterministic JSON audit for one validated candidate ledger."""

    audit = audit_source_candidate_catalog(catalog_path)
    if not audit.valid:
        raise ValueError("invalid source candidate catalog: " + "; ".join(audit.errors))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


__all__ = [
    "REQUIRED_SOURCE_CRITERIA",
    "SourceCandidateAudit",
    "SourceCandidateDecision",
    "audit_source_candidate_catalog",
    "write_source_candidate_audit",
]
