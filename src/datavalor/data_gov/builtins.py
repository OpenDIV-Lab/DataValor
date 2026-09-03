"""Dependency-free governance components used by the stage-1 workflow.

These implementations are intentionally small but operational: they read the
configured product, infer a portable schema, calculate a canonical checksum,
keep an in-memory catalog, and enforce purpose/rights decisions.  External
catalogs and scanners can replace them through the existing adapter interfaces.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, canonical_record_hash

from .interfaces import MetadataCatalog, MetadataExtractor, PolicyEvaluator, SecurityScanner
from .models import (
    CatalogQuery,
    FieldSchema,
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    MetadataRecord,
    SecurityReport,
    Severity,
)


def _records(product: DataProduct, context: RunContext) -> list[dict[str, Any]]:
    configured = context.config.get("records")
    if configured is not None:
        return [dict(row) for row in configured]
    from .data_product import adapter_from_uri

    return [dict(row) for row in adapter_from_uri(product.data.uri).records()]


def _field_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "unknown"
    if all(isinstance(value, bool) for value in present):
        return "boolean"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
        return "number"
    if all(isinstance(value, str) for value in present):
        return "string"
    return "mixed"


def _classification(name: str) -> tuple[str | None, str | None]:
    lowered = name.lower()
    if lowered in {"email", "email_address", "mail"} or "email" in lowered:
        return "email", "personal.email"
    if "phone" in lowered or "mobile" in lowered:
        return "phone", "personal.phone"
    if lowered in {"name", "full_name", "real_name"}:
        return "name", "personal.name"
    if lowered in {"lat", "latitude", "lon", "longitude"}:
        return "location", "geo.coordinate"
    if lowered.endswith("_id") or lowered == "id":
        return "identifier", "identifier"
    return None, None


class LocalMetadataExtractor(MetadataExtractor):
    """Inspect local products and produce schema, count and checksum facts."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("local.metadata_extractor", "1.0.0", "data_gov", "metadata_extractor", capabilities=("schema", "checksum", "classification"))

    def inspect(self, product: DataProduct, context: RunContext) -> MetadataRecord:
        rows = _records(product, context)
        digest, count = canonical_record_hash(rows)
        names = sorted({str(key) for row in rows for key in row})
        fields: list[FieldSchema] = []
        for name in names:
            values = [row.get(name) for row in rows]
            classification, semantic_type = _classification(name)
            fields.append(FieldSchema(name, _field_type(values), any(value is None for value in values), semantic_type, classification, metadata={"missing_count": sum(value is None for value in values), "distinct_count": len({str(value) for value in values if value is not None})}))
        return MetadataRecord(
            product.product_id,
            tuple(fields),
            product.owner_id,
            product.data.uri,
            product.metadata.get("license_id"),
            properties={"format": product.data.format, "record_count": count, "sha256": digest, "tags": product.tags, "rights": product.rights.purposes, "run_id": context.run_id},
        )


class InMemoryMetadataCatalog(MetadataCatalog):
    """A deterministic catalog useful for local pipelines and tests."""

    def __init__(self) -> None:
        self._records: dict[str, MetadataRecord] = {}

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("memory.metadata_catalog", "1.0.0", "data_gov", "metadata_catalog", capabilities=("upsert", "search"))

    def upsert(self, record: MetadataRecord, context: RunContext) -> MetadataRecord:
        del context
        self._records[record.product_id] = record
        return record

    def get(self, product_id: str, context: RunContext) -> MetadataRecord | None:
        del context
        return self._records.get(product_id)

    def search(self, query: CatalogQuery, context: RunContext) -> tuple[MetadataRecord, ...]:
        del context
        text = (query.text or "").lower()
        owners = set(query.owners)
        tags = set(query.tags)
        matches: list[MetadataRecord] = []
        for record in self._records.values():
            if owners and record.owner_id not in owners:
                continue
            record_tags = set(record.properties.get("tags", ()))
            haystack = " ".join((record.product_id, record.source or "", str(record.properties)))
            if text and text not in haystack.lower():
                continue
            if tags and not tags.issubset(record_tags):
                continue
            if query.classifications:
                classifications = {
                    field.classification
                    for field in record.fields
                    if field.classification
                }
                if not set(query.classifications).issubset(classifications):
                    continue
            matches.append(record)
        return tuple(sorted(matches, key=lambda item: item.product_id)[: max(0, query.limit)])


class RightsPolicyEvaluator(PolicyEvaluator):
    """Apply purpose, commercial, redistribution and expiry constraints."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("rights.policy_evaluator", "1.0.0", "data_gov", "policy_evaluator", capabilities=("purpose", "expiry", "commercial_use"))

    def evaluate(self, product: DataProduct, operation: str, metadata: MetadataRecord | None, context: RunContext) -> GovernanceReport:
        rights = product.rights
        findings: list[GovernanceFinding] = []
        requires_review = False
        now = datetime.now(timezone.utc)
        if not rights.purposes:
            requires_review = True
            findings.append(GovernanceFinding("rights.purpose_missing", "rights", Severity.MEDIUM, "未声明授权用途，无法自动放行", remediation="补充用途和适用范围"))
        if rights.valid_until is not None:
            # Rights can originate from JSON/YAML and therefore occasionally
            # arrive as a naive datetime.  Treat it as UTC instead of letting
            # Python raise a hard-to-diagnose naive/aware comparison error.
            valid_until = rights.valid_until
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)
            if valid_until < now:
                findings.append(GovernanceFinding("rights.expired", "rights", Severity.HIGH, "数据产品授权已过期", remediation="更新授权或停止使用"))
        if rights.purposes and operation not in rights.purposes:
            findings.append(GovernanceFinding("rights.purpose_not_allowed", "rights", Severity.HIGH, f"用途 {operation!r} 不在授权用途内", remediation="申请该用途授权"))
        if operation in {"commercial", "commercial_use", "sale"} and rights.commercial_use is False:
            findings.append(GovernanceFinding("rights.commercial_denied", "rights", Severity.HIGH, "授权不允许商业使用"))
        if operation in {"redistribution", "resale"} and rights.redistribution is False:
            findings.append(GovernanceFinding("rights.redistribution_denied", "rights", Severity.HIGH, "授权不允许再分发"))
        hard_denial = any(item.severity in {Severity.HIGH, Severity.CRITICAL} for item in findings)
        decision = GovernanceDecision.DENY if hard_denial else GovernanceDecision.REVIEW if requires_review else GovernanceDecision.ALLOW
        return GovernanceReport(product.product_id, decision, policies=(operation, "rights"), findings=tuple(findings), diagnostics={"run_id": context.run_id, "metadata_available": metadata is not None})


class SensitiveFieldScanner(SecurityScanner):
    """Detect obvious sensitive fields without pretending to be a legal classifier."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.sensitive_field_scanner", "1.0.0", "data_gov", "security_scanner", capabilities=("field_classification",))

    def scan(self, product: DataProduct, policies: Mapping[str, Any], context: RunContext) -> SecurityReport:
        record = LocalMetadataExtractor().inspect(product, context)
        findings = tuple(
            GovernanceFinding("sensitive.field", "privacy", Severity.MEDIUM, f"字段 {field.name} 可能包含敏感信息", field.name, "脱敏、聚合或限制用途", evidence=(Evidence("field.schema", summary=field.name),))
            for field in record.fields
            if field.classification in {"email", "phone", "name", "location"}
        )
        return SecurityReport(product.product_id, findings, tuple(field.name for field in record.fields), {"run_id": context.run_id, "policy_keys": tuple(policies)})


__all__ = ["InMemoryMetadataCatalog", "LocalMetadataExtractor", "RightsPolicyEvaluator", "SensitiveFieldScanner"]
