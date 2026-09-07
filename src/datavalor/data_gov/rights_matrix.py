"""Explicit rights-matrix evaluation for query, train, derive and sale flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from datavalor.core import ActorProfile, DataProduct, RightsBundle, TaskContext

from .models import (
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    MetadataRecord,
    Severity,
)


@dataclass(frozen=True)
class RightsEvaluation:
    report: GovernanceReport
    operation: str
    evaluated_at: datetime
    expiry: datetime | None
    purpose_status: str
    commercial_status: str
    redistribution_status: str
    territory_status: str


def rights_intersection(*bundles: RightsBundle) -> RightsBundle:
    """Return rights common to every bundle; ``None`` flags remain restrictive."""
    if not bundles:
        return RightsBundle()
    purposes = set(bundles[0].purposes)
    jurisdictions = set(bundles[0].jurisdictions)
    for bundle in bundles[1:]:
        purposes &= set(bundle.purposes)
        jurisdictions &= set(bundle.jurisdictions)
    commercial = all(bundle.commercial_use is True for bundle in bundles)
    redistribution = all(bundle.redistribution is True for bundle in bundles)
    valid = [value if value.tzinfo else value.replace(tzinfo=timezone.utc) for bundle in bundles if (value := bundle.valid_until) is not None]
    return RightsBundle(tuple(sorted(purposes)), commercial, redistribution, bundles[0].exclusivity, min(valid) if valid else None, tuple(sorted(jurisdictions)), {"intersected": len(bundles)})


def rights_expiry_window(bundle: RightsBundle, evaluated_at: datetime | None = None) -> float | None:
    if bundle.valid_until is None:
        return None
    now = evaluated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    expiry = bundle.valid_until if bundle.valid_until.tzinfo else bundle.valid_until.replace(tzinfo=timezone.utc)
    return max(0.0, (expiry - now).total_seconds())


def explain_rights_failure(evaluation: RightsEvaluation | GovernanceReport) -> tuple[str, ...]:
    report = evaluation.report if isinstance(evaluation, RightsEvaluation) else evaluation
    return tuple(f"{finding.code}: {finding.message}" for finding in report.findings if finding.severity in {Severity.HIGH, Severity.CRITICAL})


class RightsMatrixEvaluator:
    """Evaluate product rights against actor, task and buyer constraints."""

    def evaluate(
        self,
        product: DataProduct,
        operation: str,
        actor: ActorProfile | None = None,
        task: TaskContext | None = None,
        requested: RightsBundle | None = None,
        evaluated_at: datetime | None = None,
        metadata: MetadataRecord | None = None,
        policy: dict[str, Any] | None = None,
    ) -> RightsEvaluation:
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        rights = product.rights
        findings: list[GovernanceFinding] = []
        operation = operation.lower().strip()
        purpose = (task.objective if task else None) or (requested.purposes[0] if requested and requested.purposes else operation)
        purpose_status = "allow"; commercial_status = "allow"; redistribution_status = "allow"; territory_status = "allow"
        if not rights.purposes:
            purpose_status = "review"
            findings.append(GovernanceFinding("rights.purpose_missing", "purpose", Severity.MEDIUM, "产品未声明授权用途，需人工确认", remediation="补充用途白名单"))
        elif (purpose not in rights.purposes and operation not in rights.purposes) or (
            requested
            and requested.purposes
            and not set(requested.purposes).issubset(set(rights.purposes))
        ):
            purpose_status = "deny"
            findings.append(GovernanceFinding("rights.purpose_not_allowed", "purpose", Severity.HIGH, f"用途 {purpose!r} 不在授权矩阵内", remediation="申请用途授权", details={"allowed": rights.purposes}))
        commercial_requested = operation in {"commercial", "commercial_use", "sale", "sell", "quote"} or bool(requested and requested.commercial_use)
        if commercial_requested and rights.commercial_use is not True:
            commercial_status = "deny" if rights.commercial_use is False else "review"
            code = "rights.commercial_denied" if rights.commercial_use is False else "rights.commercial_missing"
            findings.append(GovernanceFinding(code, "commercial", Severity.HIGH if rights.commercial_use is False else Severity.MEDIUM, "授权未允许商业使用" if rights.commercial_use is False else "商业使用状态未声明"))
        redistribution_requested = operation in {"redistribution", "resale", "publish", "share"} or bool(requested and requested.redistribution)
        if redistribution_requested and rights.redistribution is not True:
            redistribution_status = "deny" if rights.redistribution is False else "review"
            code = "rights.redistribution_denied" if rights.redistribution is False else "rights.redistribution_missing"
            findings.append(GovernanceFinding(code, "redistribution", Severity.HIGH if rights.redistribution is False else Severity.MEDIUM, "授权不允许再分发" if rights.redistribution is False else "再分发状态未声明"))
        requested_jurisdictions = set((requested.jurisdictions if requested else ()) or (task.constraints.get("jurisdictions", ()) if task else ()))
        if requested_jurisdictions:
            if not rights.jurisdictions:
                territory_status = "review"
                findings.append(GovernanceFinding("rights.jurisdiction_missing", "territory", Severity.MEDIUM, "未声明适用司法辖区"))
            elif not requested_jurisdictions.issubset(set(rights.jurisdictions)):
                territory_status = "deny"
                findings.append(GovernanceFinding("rights.jurisdiction_denied", "territory", Severity.HIGH, "请求辖区超出授权范围", details={"requested": sorted(requested_jurisdictions), "allowed": rights.jurisdictions}))
        if rights.valid_until is not None:
            expiry = rights.valid_until if rights.valid_until.tzinfo else rights.valid_until.replace(tzinfo=timezone.utc)
            if expiry <= now:
                findings.append(GovernanceFinding("rights.expired", "expiry", Severity.HIGH, "授权已过期", remediation="续签后重试"))
        if actor and actor.constraints.get("forbid_redistribution") and redistribution_requested:
            findings.append(GovernanceFinding("buyer.redistribution_constraint", "buyer", Severity.HIGH, "买方约束禁止再分发"))
        if task and task.constraints.get("required_purpose") and task.constraints["required_purpose"] not in rights.purposes:
            findings.append(GovernanceFinding("task.purpose_constraint", "purpose", Severity.HIGH, "任务要求用途不在授权范围"))
        hard = any(f.severity in {Severity.HIGH, Severity.CRITICAL} for f in findings)
        review = any(f.severity == Severity.MEDIUM for f in findings)
        decision = GovernanceDecision.DENY if hard else GovernanceDecision.REVIEW if review else GovernanceDecision.ALLOW
        report = GovernanceReport(product.product_id, decision, policies=("rights_matrix", operation), findings=tuple(findings), diagnostics={"run_id": policy.get("run_id") if policy else None, "metadata_available": metadata is not None, "actor_id": actor.actor_id if actor else None, "task_id": task.task_id if task else None})
        return RightsEvaluation(report, operation, now, rights.valid_until, purpose_status, commercial_status, redistribution_status, territory_status)


def evaluate_rights_matrix(*args: Any, **kwargs: Any) -> RightsEvaluation:
    return RightsMatrixEvaluator().evaluate(*args, **kwargs)
