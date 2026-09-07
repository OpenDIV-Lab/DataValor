"""DataGov 扩展示例：血缘影响、权利矩阵与版本审计。

运行：``PYTHONPATH=src python examples/12_datagov_lineage_rights_audit.py``
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from datavalor.core import (
    ActorProfile,
    ActorRole,
    ArtifactRef,
    DataProduct,
    DataReference,
    RightsBundle,
    TaskContext,
)
from datavalor.data_gov import (
    FieldSchema,
    GovernanceFinding,
    GovernanceReport,
    LineageEdge,
    LineageNode,
    MetadataRecord,
    RightsMatrixEvaluator,
    SecurityReport,
    Severity,
    build_governance_audit,
    build_lineage_graph,
    compare_metadata_records,
    explain_rights_failure,
)

ROOT = Path(__file__).resolve().parents[1]


def product(version: str, checksum: str, rights: RightsBundle) -> DataProduct:
    return DataProduct("customer-demand", f"Customer demand {version}", DataReference("memory://demand", "jsonl", checksum=checksum, record_count=1000), "analytics-team", version=version, rights=rights, tags=("retail", "valuation"))


def metadata(version: str, checksum: str, include_email: bool) -> MetadataRecord:
    fields = [FieldSchema("region", "string"), FieldSchema("demand", "number")]
    if include_email:
        fields.append(FieldSchema("email", "string", nullable=True, classification="email", semantic_type="personal.email"))
    return MetadataRecord("customer-demand", tuple(fields), owner_id="analytics-team", source="memory://demand", properties={"version": version, "record_count": 1000, "sha256": checksum, "rights": ("analysis", "query") if version == "1" else ("analysis",)})


def main() -> None:
    rights_v1 = RightsBundle(purposes=("analysis", "query", "model_training"), commercial_use=True, redistribution=False, jurisdictions=("CN", "SG"), valid_until=datetime.now(timezone.utc) + timedelta(days=30))
    rights_v2 = RightsBundle(purposes=("analysis",), commercial_use=False, redistribution=False, jurisdictions=("CN",), valid_until=datetime.now(timezone.utc) + timedelta(days=30))
    _, p2 = product("1", "sha-v1", rights_v1), product("2", "sha-v2", rights_v2)
    m1, m2 = metadata("1", "sha-v1", True), metadata("2", "sha-v2", False)

    lineage = build_lineage_graph(
        (p2,),
        (m2,),
        edges=(
            LineageEdge("customer-source", "customer-demand", "derived_from", {"transformation": "deduplicate+aggregate", "config_sha256": "cfg-123"}),
            LineageEdge("customer-demand", "eval:customer-demand:v2", "produces", {"metric": "completeness"}),
            LineageEdge("eval:customer-demand:v2", "value:customer-demand:v2", "feeds", {"method": "task_utility"}),
            LineageEdge("value:customer-demand:v2", "quote:customer-demand:v2", "feeds", {"method": "quality_adjusted_quote"}),
        ),
        artifact_nodes=(LineageNode("customer-source", "source", "CRM export"), LineageNode("eval:customer-demand:v2", "evaluation"), LineageNode("value:customer-demand:v2", "valuation"), LineageNode("quote:customer-demand:v2", "quote")),
    )
    diff = compare_metadata_records(m1, m2)
    evaluator = RightsMatrixEvaluator()
    actor = ActorProfile("buyer-01", ActorRole.BUYER, constraints={"forbid_redistribution": True})
    task = TaskContext("forecast-2026", "model_training", constraints={"jurisdictions": ("SG",)})
    rights_check = evaluator.evaluate(p2, "model_training", actor=actor, task=task, evaluated_at=datetime.now(timezone.utc))
    governance = GovernanceReport(p2.product_id, rights_check.report.decision, findings=rights_check.report.findings, diagnostics=rights_check.report.diagnostics)
    security = SecurityReport(p2.product_id, (GovernanceFinding("sensitive.field", "privacy", Severity.MEDIUM, "email 已在 v2 移除"),))
    audit = build_governance_audit(p2.product_id, metadata=m2, governance=governance, security=security, lineage=lineage, version_diff=diff, artifacts=(ArtifactRef("eval:customer-demand:v2", "evaluation", "1"), ArtifactRef("value:customer-demand:v2", "valuation", "1"), ArtifactRef("quote:customer-demand:v2", "quote", "1")))

    output = {"rights": {"decision": rights_check.report.decision.value, "statuses": {"purpose": rights_check.purpose_status, "commercial": rights_check.commercial_status, "territory": rights_check.territory_status}, "failures": explain_rights_failure(rights_check)}, "version_diff": asdict(diff), "lineage": {"digest": lineage.lineage_digest(), "upstream_of_quote": [node.node_id for node in lineage.trace_upstream("quote:customer-demand:v2")], "affected_from_source": [node.node_id for node in lineage.affected_artifacts("customer-source", ("evaluation", "valuation", "quote"))]}, "audit": audit.summary()}
    out = ROOT / "outputs/datagov-extension/result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"decision": output["rights"]["decision"], "breaking_changes": output["version_diff"]["breaking_changes"], "affected_artifacts": output["lineage"]["affected_from_source"], "output": str(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
