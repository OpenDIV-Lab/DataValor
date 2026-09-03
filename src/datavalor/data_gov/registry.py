"""Typed extension registries for DataGov."""

from datavalor.core import Registry

from .interfaces import (
    DataCleaner,
    DataStandardizer,
    MetadataCatalog,
    MetadataExtractor,
    PolicyEvaluator,
    SecurityScanner,
)

METADATA_EXTRACTORS = Registry[MetadataExtractor]("data_gov.metadata_extractors")
METADATA_CATALOGS = Registry[MetadataCatalog]("data_gov.metadata_catalogs")
STANDARDIZERS = Registry[DataStandardizer]("data_gov.standardizers")
CLEANERS = Registry[DataCleaner]("data_gov.cleaners")
SECURITY_SCANNERS = Registry[SecurityScanner]("data_gov.security_scanners")
POLICY_EVALUATORS = Registry[PolicyEvaluator]("data_gov.policy_evaluators")

