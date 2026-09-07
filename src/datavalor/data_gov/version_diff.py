"""Schema, rights and statistics diffing for DataGov product versions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from datavalor.core import DataProduct

from .models import FieldSchema, MetadataRecord


@dataclass(frozen=True)
class MetadataDiff:
    product_id: str
    left_version: str | None
    right_version: str | None
    schema_changes: tuple[Mapping[str, Any], ...] = ()
    rights_changes: tuple[Mapping[str, Any], ...] = ()
    source_changes: tuple[Mapping[str, Any], ...] = ()
    statistics_changes: tuple[Mapping[str, Any], ...] = ()
    metadata_changes: tuple[Mapping[str, Any], ...] = ()
    breaking_changes: tuple[str, ...] = ()
    quality_re_evaluation_required: bool = False
    value_re_evaluation_required: bool = False
    price_re_evaluation_required: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.schema_changes or self.rights_changes or self.source_changes or self.statistics_changes or self.metadata_changes)


def _field_map(record: MetadataRecord | None) -> dict[str, FieldSchema]:
    return {field.name: field for field in (record.fields if record else ())}


def compare_metadata_records(left: MetadataRecord, right: MetadataRecord) -> MetadataDiff:
    schema: list[Mapping[str, Any]] = []
    breaking: list[str] = []
    old, new = _field_map(left), _field_map(right)
    for name in sorted(set(new) - set(old)):
        schema.append({"field": name, "change": "added", "new": new[name].__dict__})
    for name in sorted(set(old) - set(new)):
        schema.append({"field": name, "change": "removed", "old": old[name].__dict__}); breaking.append(f"field_removed:{name}")
    for name in sorted(set(old) & set(new)):
        a, b = old[name], new[name]
        for attr in ("data_type", "nullable", "semantic_type", "classification", "constraints"):
            if getattr(a, attr) != getattr(b, attr):
                schema.append({"field": name, "change": attr, "old": getattr(a, attr), "new": getattr(b, attr)})
                if attr in {"data_type", "semantic_type", "classification", "nullable", "constraints"}:
                    breaking.append(f"{attr}_changed:{name}")
    stats: list[Mapping[str, Any]] = []
    for key in ("record_count", "sha256"):
        if left.properties.get(key) != right.properties.get(key):
            stats.append({"key": key, "old": left.properties.get(key), "new": right.properties.get(key)})
    source: list[Mapping[str, Any]] = []
    for key in ("source", "owner_id", "license_id"):
        a = getattr(left, key, None); b = getattr(right, key, None)
        if a != b:
            source.append({"key": key, "old": a, "new": b})
    metadata = tuple({"key": key, "old": left.properties.get(key), "new": right.properties.get(key)} for key in sorted(set(left.properties) | set(right.properties)) if left.properties.get(key) != right.properties.get(key) and key not in {"record_count", "sha256", "rights"})
    rights = tuple({"key": key, "old": left.properties.get("rights"), "new": right.properties.get("rights")} for key in ("rights",) if left.properties.get(key) != right.properties.get(key))
    quality = bool(schema or stats)
    value = bool(schema or stats or source)
    price = bool(rights or source or stats or schema)
    return MetadataDiff(left.product_id, left.properties.get("version"), right.properties.get("version"), tuple(schema), rights, tuple(source), tuple(stats), metadata, tuple(sorted(set(breaking))), quality, value, price)


def compare_products(left: DataProduct, right: DataProduct, left_metadata: MetadataRecord | None = None, right_metadata: MetadataRecord | None = None) -> MetadataDiff:
    """Compare products even when catalog metadata is unavailable."""
    lm = left_metadata or MetadataRecord(left.product_id, owner_id=left.owner_id, source=left.data.uri, license_id=left.metadata.get("license_id"), properties={"record_count": left.data.record_count, "sha256": left.data.checksum, "rights": left.rights.purposes, "version": left.version})
    rm = right_metadata or MetadataRecord(right.product_id, owner_id=right.owner_id, source=right.data.uri, license_id=right.metadata.get("license_id"), properties={"record_count": right.data.record_count, "sha256": right.data.checksum, "rights": right.rights.purposes, "version": right.version})
    diff = compare_metadata_records(lm, rm)
    rights = list(diff.rights_changes)
    if left.rights != right.rights:
        rights.append({"old": left.rights.__dict__, "new": right.rights.__dict__})
    breaking = list(diff.breaking_changes)
    if left.data.schema_ref != right.data.schema_ref:
        breaking.append("schema_ref_changed")
    return MetadataDiff(left.product_id, left.version, right.version, diff.schema_changes, tuple(rights), diff.source_changes, diff.statistics_changes, diff.metadata_changes, tuple(sorted(set(breaking))), diff.quality_re_evaluation_required or bool(rights), diff.value_re_evaluation_required or bool(rights), diff.price_re_evaluation_required or bool(rights))


def quality_impact_summary(diff: MetadataDiff) -> dict[str, Any]:
    return {"changed": diff.changed, "breaking_changes": diff.breaking_changes, "schema_change_count": len(diff.schema_changes), "rights_change_count": len(diff.rights_changes), "statistics_change_count": len(diff.statistics_changes), "re_evaluate": {"quality": diff.quality_re_evaluation_required, "value": diff.value_re_evaluation_required, "price": diff.price_re_evaluation_required}}


def requires_re_evaluation(diff: MetadataDiff, stage: str) -> bool:
    key = {"quality": diff.quality_re_evaluation_required, "eval": diff.quality_re_evaluation_required, "value": diff.value_re_evaluation_required, "price": diff.price_re_evaluation_required, "quote": diff.price_re_evaluation_required}.get(stage.lower())
    if key is None:
        raise ValueError(f"unknown evaluation stage: {stage}")
    return key

