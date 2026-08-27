"""Models for governance, standardization, cleaning, security, and metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from datavalor.core import ArtifactRef, DataProduct, DataReference, Evidence


class Severity(str, Enum):
    """Portable severity scale for governance and security findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceDecision(str, Enum):
    """Result of applying governance or access policies."""

    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"


@dataclass(frozen=True)
class FieldSchema:
    """Governance-oriented description of one logical field."""

    name: str
    data_type: str
    nullable: bool | None = None
    semantic_type: str | None = None
    classification: str | None = None
    constraints: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetadataRecord:
    """Extracted metadata suitable for a DataValor catalog implementation."""

    product_id: str
    fields: tuple[FieldSchema, ...] = ()
    owner_id: str | None = None
    source: str | None = None
    license_id: str | None = None
    lineage: tuple[ArtifactRef, ...] = ()
    properties: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceFinding:
    """One auditable policy, quality-of-governance, or compliance finding."""

    code: str
    dimension: str
    severity: Severity
    message: str
    field_name: str | None = None
    remediation: str | None = None
    evidence: tuple[Evidence, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceReport:
    """Policy decision and evidence for a governed operation."""

    product_id: str
    decision: GovernanceDecision
    policies: tuple[str, ...] = ()
    findings: tuple[GovernanceFinding, ...] = ()
    metadata_ref: ArtifactRef | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StandardDefinition:
    """Named schema, formatting, or semantic standard to be applied."""

    standard_id: str
    version: str
    rules: Mapping[str, Any]


@dataclass(frozen=True)
class TransformationStep:
    """Declarative cleaning or standardization operation."""

    operation: str
    fields: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass(frozen=True)
class TransformationPlan:
    """Auditable plan produced before mutating or materializing data."""

    product_id: str
    purpose: str
    steps: tuple[TransformationStep, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransformationResult:
    """Reference to transformed data plus a change audit."""

    product: DataProduct
    output: DataReference
    plan: TransformationPlan
    changed_records: int | None = None
    rejected_records: int | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SecurityReport:
    """Security and privacy findings that remain separate from policy decisions."""

    product_id: str
    findings: tuple[GovernanceFinding, ...]
    scanned_fields: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogQuery:
    """Portable metadata search request."""

    text: str | None = None
    owners: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    classifications: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 100
