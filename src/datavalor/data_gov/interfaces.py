"""Extension interfaces for the DataGov module."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Mapping

from datavalor.core import BaseComponent, DataProduct, RunContext

from .models import (
    CatalogQuery,
    GovernanceReport,
    MetadataRecord,
    SecurityReport,
    StandardDefinition,
    TransformationPlan,
    TransformationResult,
)


class MetadataExtractor(BaseComponent):
    """Extract technical, semantic, rights, and lineage metadata."""

    @abstractmethod
    def inspect(self, product: DataProduct, context: RunContext) -> MetadataRecord:
        """Inspect a product without changing its underlying data."""


class MetadataCatalog(BaseComponent):
    """Store and discover governed metadata independently of a vendor platform."""

    @abstractmethod
    def upsert(self, record: MetadataRecord, context: RunContext) -> MetadataRecord:
        """Create or update one metadata record."""

    @abstractmethod
    def get(self, product_id: str, context: RunContext) -> MetadataRecord | None:
        """Return metadata for a product if visible to the caller."""

    @abstractmethod
    def search(self, query: CatalogQuery, context: RunContext) -> tuple[MetadataRecord, ...]:
        """Search records subject to access and visibility rules."""


class DataStandardizer(BaseComponent):
    """Plan and apply schema, format, or semantic standardization."""

    @abstractmethod
    def plan(
        self,
        product: DataProduct,
        standard: StandardDefinition,
        context: RunContext,
    ) -> TransformationPlan:
        """Produce an auditable standardization plan."""

    @abstractmethod
    def transform(
        self,
        product: DataProduct,
        plan: TransformationPlan,
        context: RunContext,
    ) -> TransformationResult:
        """Materialize a standardized product according to an approved plan."""


class DataCleaner(BaseComponent):
    """Detect and repair records under explicit, reproducible cleaning rules."""

    @abstractmethod
    def plan(
        self,
        product: DataProduct,
        rules: Mapping[str, Any],
        context: RunContext,
    ) -> TransformationPlan:
        """Produce a cleaning plan without changing data."""

    @abstractmethod
    def clean(
        self,
        product: DataProduct,
        plan: TransformationPlan,
        context: RunContext,
    ) -> TransformationResult:
        """Apply a reviewed cleaning plan and return a new data reference."""


class SecurityScanner(BaseComponent):
    """Detect sensitive fields, unsafe content, leakage, or security risks."""

    @abstractmethod
    def scan(
        self,
        product: DataProduct,
        policies: Mapping[str, Any],
        context: RunContext,
    ) -> SecurityReport:
        """Return evidence-backed security and privacy findings."""


class PolicyEvaluator(BaseComponent):
    """Evaluate whether a proposed operation is allowed, denied, or needs review."""

    @abstractmethod
    def evaluate(
        self,
        product: DataProduct,
        operation: str,
        metadata: MetadataRecord | None,
        context: RunContext,
    ) -> GovernanceReport:
        """Apply named policies and return a traceable decision."""

