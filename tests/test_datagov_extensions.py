from datetime import datetime, timedelta, timezone

import pytest

from datavalor.core import (
    DataProduct,
    DataReference,
    RightsBundle,
    TaskContext,
)
from datavalor.data_gov import (
    FieldSchema,
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    LineageEdge,
    LineageGraph,
    LineageNode,
    MetadataRecord,
    RightsMatrixEvaluator,
    SecurityReport,
    Severity,
    build_governance_audit,
    build_lineage_graph,
    compare_lineage,
    compare_metadata_records,
    compare_products,
    explain_rights_failure,
    requires_re_evaluation,
)


def _product(version="1", rights=None, checksum=None, count=None):
    return DataProduct("p", "Product", DataReference("memory://p", "json", checksum=checksum, record_count=count), "owner", version=version, rights=rights or RightsBundle())


def test_lineage_walk_topological_impact_and_digest():
    graph = LineageGraph((LineageNode("source", "source"), LineageNode("raw", "dataset"), LineageNode("eval", "evaluation"), LineageNode("quote", "quote")), (LineageEdge("source", "raw", metadata={"transformation": "ingest"}), LineageEdge("raw", "eval", metadata={"transformation": "profile"}), LineageEdge("eval", "quote", metadata={"transformation": "price"})))
    assert [node.node_id for node in graph.trace_upstream("quote")] == ["eval", "raw", "source"]
    assert [node.node_id for node in graph.trace_downstream("raw")] == ["eval", "quote"]
    assert [node.node_id for node in graph.affected_artifacts("raw", ("evaluation",))] == ["eval"]
    assert graph.topological_order() == ("source", "raw", "eval", "quote")
    assert len(graph.lineage_digest()) == 64
    assert graph.validate() == ()
    changed = LineageGraph(graph.nodes, graph.edges[:-1] + (LineageEdge("raw", "quote", metadata={"transformation": "shortcut"}),))
    assert compare_lineage(graph, changed)["edges_added"]


def test_lineage_rejects_cycles_and_missing_nodes():
    graph = LineageGraph((LineageNode("a", "source"), LineageNode("b", "dataset")))
    with pytest.raises(ValueError):
        graph.add_edge(LineageEdge("a", "a"))
    graph.add_edge(LineageEdge("a", "b"))
    graph._edges.append(LineageEdge("b", "a"))  # emulate a bad external catalog snapshot
    with pytest.raises(ValueError, match="cycle"):
        graph.topological_order()
    with pytest.raises(KeyError):
        graph.trace_upstream("missing")
    with pytest.raises(KeyError):
        LineageGraph((LineageNode("a", "source"),), (LineageEdge("a", "missing"),))


def test_build_lineage_from_metadata_refs():
    from datavalor.core import ArtifactRef

    record = MetadataRecord("p", lineage=(ArtifactRef("raw", "dataset", "1"),), source="memory://raw")
    graph = build_lineage_graph((_product(),), (record,))
    assert graph.trace_upstream("p")[0].node_id == "raw"


def test_rights_matrix_deny_review_and_task_constraints():
    rights = RightsBundle(purposes=("analysis",), commercial_use=False, redistribution=False, valid_until=datetime.now(timezone.utc) + timedelta(hours=1), jurisdictions=("CN",))
    product = _product(rights=rights)
    evaluator = RightsMatrixEvaluator()
    denied = evaluator.evaluate(product, "sale", task=TaskContext("t", "analysis", constraints={"jurisdictions": ("US",)}), evaluated_at=datetime.now(timezone.utc))
    assert denied.report.decision is GovernanceDecision.DENY
    assert {finding.code for finding in denied.report.findings} >= {"rights.commercial_denied", "rights.jurisdiction_denied"}
    assert explain_rights_failure(denied)
    review = evaluator.evaluate(_product(), "query", evaluated_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert review.report.decision is GovernanceDecision.REVIEW


def test_version_diff_classification_and_re_evaluation():
    old = MetadataRecord("p", (FieldSchema("id", "string"), FieldSchema("score", "number")), properties={"record_count": 10, "sha256": "a", "rights": ("analysis",), "version": "1"})
    new = MetadataRecord("p", (FieldSchema("id", "string"), FieldSchema("score", "string"), FieldSchema("label", "string")), properties={"record_count": 12, "sha256": "b", "rights": ("query",), "version": "2"})
    diff = compare_metadata_records(old, new)
    assert any(change["change"] == "added" for change in diff.schema_changes)
    assert "data_type_changed:score" in diff.breaking_changes
    assert diff.rights_changes and diff.quality_re_evaluation_required
    assert requires_re_evaluation(diff, "value")
    with pytest.raises(ValueError):
        requires_re_evaluation(diff, "unknown")
    product_diff = compare_products(_product("1", checksum="a", count=10), _product("2", checksum="b", count=12))
    assert product_diff.statistics_changes


def test_audit_bundle_combines_findings_and_digest():
    report = GovernanceReport("p", GovernanceDecision.ALLOW, findings=())
    security = SecurityReport("p", (GovernanceFinding("sensitive", "privacy", Severity.HIGH, "blocked"),))
    bundle = build_governance_audit("p", governance=report, security=security, diagnostics={"source": "test"})
    assert bundle.decision is GovernanceDecision.DENY  # security hard findings take precedence
    assert bundle.summary()["finding_counts"]["high"] == 1
    assert len(bundle.digest()) == 64
