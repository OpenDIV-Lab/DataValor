"""DataGov: governance, standards, cleaning, security, and metadata."""

from .audit import GovernanceAuditBundle, audit_status, build_governance_audit, summarize_findings
from .builtins import (
    InMemoryMetadataCatalog,
    LocalMetadataExtractor,
    RightsPolicyEvaluator,
    SensitiveFieldScanner,
)
from .data_product import (
    CSVAdapter,
    DataProductAdapter,
    DataProductMetadata,
    DirectoryAdapter,
    IterableAdapter,
    JSONAdapter,
    JSONLAdapter,
    ParquetAdapter,
    adapter_from_uri,
    canonical_record_hash,
    load_manifest_product,
)
from .interfaces import (
    DataCleaner,
    DataStandardizer,
    MetadataCatalog,
    MetadataExtractor,
    PolicyEvaluator,
    SecurityScanner,
)
from .lineage import (
    LineageEdge,
    LineageGraph,
    LineageNode,
    affected_artifacts,
    build_lineage_graph,
    compare_lineage,
    trace_downstream,
    trace_upstream,
)
from .market_readiness import (
    ArtifactStaleness,
    ArtifactStalenessEvaluator,
    RightsCompatibility,
    RightsCompatibilityEvaluator,
    RightsRestrictionScore,
    RightsRestrictivenessScorer,
)
from .models import (
    CatalogQuery,
    FieldSchema,
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    MetadataRecord,
    SecurityReport,
    Severity,
    StandardDefinition,
    TransformationPlan,
    TransformationResult,
    TransformationStep,
)
from .registry import (
    CLEANERS,
    METADATA_CATALOGS,
    METADATA_EXTRACTORS,
    POLICY_EVALUATORS,
    SECURITY_SCANNERS,
    STANDARDIZERS,
)
from .rights_matrix import (
    RightsEvaluation,
    RightsMatrixEvaluator,
    evaluate_rights_matrix,
    explain_rights_failure,
    rights_expiry_window,
    rights_intersection,
)
from .version_diff import (
    MetadataDiff,
    compare_metadata_records,
    compare_products,
    quality_impact_summary,
    requires_re_evaluation,
)

for _component, _registry in (
    (LocalMetadataExtractor, METADATA_EXTRACTORS),
    (InMemoryMetadataCatalog, METADATA_CATALOGS),
    (RightsPolicyEvaluator, POLICY_EVALUATORS),
    (SensitiveFieldScanner, SECURITY_SCANNERS),
):
    if _component().spec.name not in _registry:
        _registry.register(_component().spec, _component)

__all__ = [
    "CLEANERS",
    "METADATA_CATALOGS",
    "METADATA_EXTRACTORS",
    "POLICY_EVALUATORS",
    "SECURITY_SCANNERS",
    "STANDARDIZERS",
    "CatalogQuery",
    "DataCleaner",
    "DataStandardizer",
    "FieldSchema",
    "GovernanceDecision",
    "GovernanceFinding",
    "GovernanceReport",
    "MetadataCatalog",
    "MetadataExtractor",
    "MetadataRecord",
    "PolicyEvaluator",
    "SecurityReport",
    "SecurityScanner",
    "Severity",
    "StandardDefinition",
    "TransformationPlan",
    "TransformationResult",
    "TransformationStep",
    "CSVAdapter",
    "DataProductAdapter",
    "DataProductMetadata",
    "DirectoryAdapter",
    "IterableAdapter",
    "JSONAdapter",
    "JSONLAdapter",
    "ParquetAdapter",
    "adapter_from_uri",
    "canonical_record_hash",
    "load_manifest_product",
    "InMemoryMetadataCatalog",
    "LocalMetadataExtractor",
    "RightsPolicyEvaluator",
    "SensitiveFieldScanner",
    "LineageNode", "LineageEdge", "LineageGraph", "build_lineage_graph", "trace_upstream", "trace_downstream", "affected_artifacts", "compare_lineage",
    "RightsEvaluation", "RightsMatrixEvaluator", "evaluate_rights_matrix", "rights_intersection", "rights_expiry_window", "explain_rights_failure",
    "MetadataDiff", "compare_metadata_records", "compare_products", "quality_impact_summary", "requires_re_evaluation",
    "GovernanceAuditBundle", "build_governance_audit", "summarize_findings", "audit_status",
    "ArtifactStaleness", "ArtifactStalenessEvaluator",
    "RightsCompatibility", "RightsCompatibilityEvaluator",
    "RightsRestrictionScore", "RightsRestrictivenessScorer",
]
