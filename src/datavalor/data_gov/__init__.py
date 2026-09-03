"""DataGov: governance, standards, cleaning, security, and metadata."""

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
]
