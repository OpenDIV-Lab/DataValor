"""Composable governance evidence bundle for artifact stores and approvals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from datavalor.core import ArtifactRef, canonical_sha256

from .lineage import LineageGraph
from .models import (
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    MetadataRecord,
    SecurityReport,
)
from .version_diff import MetadataDiff, quality_impact_summary


@dataclass(frozen=True)
class GovernanceAuditBundle:
    bundle_id: str
    product_id: str
    created_at: datetime
    metadata: MetadataRecord | None = None
    governance: GovernanceReport | None = None
    security: SecurityReport | None = None
    lineage_digest: str | None = None
    version_diff: MetadataDiff | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def decision(self) -> GovernanceDecision:
        if self.security and any(f.severity.value in {"high", "critical"} for f in self.security.findings):
            return GovernanceDecision.DENY
        if self.governance:
            return self.governance.decision
        return GovernanceDecision.REVIEW

    @property
    def findings(self) -> tuple[GovernanceFinding, ...]:
        return tuple((self.governance.findings if self.governance else ()) + (self.security.findings if self.security else ()))

    def summary(self) -> dict[str, Any]:
        counts = {severity: sum(1 for finding in self.findings if finding.severity.value == severity) for severity in ("info", "low", "medium", "high", "critical")}
        return {"bundle_id": self.bundle_id, "product_id": self.product_id, "decision": self.decision.value, "finding_counts": counts, "lineage_digest": self.lineage_digest, "version_diff": quality_impact_summary(self.version_diff) if self.version_diff else None, "recommendations": self.diagnostics.get("recommendations", ())}

    def digest(self) -> str:
        return canonical_sha256(self.summary())

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_governance_audit(product_id: str, metadata: MetadataRecord | None = None, governance: GovernanceReport | None = None, security: SecurityReport | None = None, lineage: LineageGraph | None = None, version_diff: MetadataDiff | None = None, artifacts: tuple[ArtifactRef, ...] = (), bundle_id: str | None = None, diagnostics: Mapping[str, Any] | None = None) -> GovernanceAuditBundle:
    recommendations: list[str] = []
    if version_diff:
        if version_diff.quality_re_evaluation_required: recommendations.append("rerun_data_eval")
        if version_diff.value_re_evaluation_required: recommendations.append("rerun_data_value")
        if version_diff.price_re_evaluation_required: recommendations.append("rerun_data_price")
    bundle_id = bundle_id or f"governance:{product_id}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    merged = dict(diagnostics or {}); merged.setdefault("recommendations", tuple(recommendations))
    return GovernanceAuditBundle(bundle_id, product_id, datetime.now(timezone.utc), metadata, governance, security, lineage.lineage_digest() if lineage else None, version_diff, artifacts, merged)


def summarize_findings(bundle: GovernanceAuditBundle) -> Mapping[str, int]:
    return bundle.summary()["finding_counts"]


def audit_status(bundle: GovernanceAuditBundle) -> str:
    return bundle.decision.value
