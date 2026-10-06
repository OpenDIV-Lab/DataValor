"""Normalized papers, repositories, and benchmark mechanism provenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .registry import MethodRegistry
from .resources import resource_path

CATALOG_DIR = resource_path("catalog")
DEFAULT_MECHANISMS = CATALOG_DIR / "mechanisms.yaml"
DEFAULT_REFERENCES = CATALOG_DIR / "references.yaml"

PROVENANCE_KINDS = frozenset(
    {
        "paper_exact",
        "official_adapter",
        "paper_variant",
        "project_implementation",
        "common_baseline",
        "allocation_oracle",
        "diagnostic_reference",
    }
)
LITERATURE_KINDS = frozenset(
    {"paper_exact", "official_adapter", "project_implementation"}
)


@dataclass(frozen=True)
class ReferenceRecord:
    reference_id: str
    kind: str
    title: str
    authors: tuple[str, ...]
    year: int
    venue: str
    url: str
    doi: str | None = None
    repository_url: str | None = None
    version: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class MechanismRecord:
    method_id: str
    family_id: str
    track: str
    implementation_kind: str
    provenance_kind: str
    reference_keys: tuple[str, ...]
    baseline_usage_reference_keys: tuple[str, ...]
    algorithm_location: str
    supported_case_types: frozenset[str]
    source: str = ""
    deviations: tuple[str, ...] = ()
    references: tuple[ReferenceRecord, ...] = ()
    baseline_usage_references: tuple[ReferenceRecord, ...] = ()

    @property
    def primary_reference(self) -> ReferenceRecord:
        if not self.references:
            raise ValueError(f"mechanism {self.method_id} has no primary reference")
        return self.references[0]


@dataclass(frozen=True)
class ProvenanceCatalog:
    references: Mapping[str, ReferenceRecord]
    mechanisms: Mapping[str, MechanismRecord]


def _load_yaml(path: str | Path, collection: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    values = raw.get(collection, ())
    if not isinstance(values, list):
        raise ValueError(f"{collection} must be a list")
    return [dict(value) for value in values]


def _unique(items: list[dict[str, Any]], key: str, label: str) -> None:
    values = [str(item.get(key, "")) for item in items]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if "" in values:
        raise ValueError(f"{label} requires {key}")
    if duplicates:
        raise ValueError(f"duplicate {label} {key}: {duplicates}")


def _reference(item: Mapping[str, Any]) -> ReferenceRecord:
    required = ("reference_id", "kind", "title", "authors", "year", "venue", "url")
    missing = [key for key in required if item.get(key) in (None, "", [])]
    if missing:
        raise ValueError(f"reference {item.get('reference_id', '<unknown>')} missing {missing}")
    return ReferenceRecord(
        reference_id=str(item["reference_id"]),
        kind=str(item["kind"]),
        title=str(item["title"]),
        authors=tuple(str(value) for value in item["authors"]),
        year=int(item["year"]),
        venue=str(item["venue"]),
        url=str(item["url"]),
        doi=str(item["doi"]) if item.get("doi") else None,
        repository_url=(str(item["repository_url"]) if item.get("repository_url") else None),
        version=str(item["version"]) if item.get("version") else None,
        license=str(item["license"]) if item.get("license") else None,
    )


def load_provenance(
    mechanism_path: str | Path = DEFAULT_MECHANISMS,
    reference_path: str | Path = DEFAULT_REFERENCES,
) -> ProvenanceCatalog:
    reference_items = _load_yaml(reference_path, "references")
    mechanism_items = _load_yaml(mechanism_path, "mechanisms")
    _unique(reference_items, "reference_id", "reference")
    _unique(mechanism_items, "method_id", "mechanism")
    references = {
        record.reference_id: record
        for record in (_reference(item) for item in reference_items)
    }
    mechanisms: dict[str, MechanismRecord] = {}
    for item in mechanism_items:
        method_id = str(item["method_id"])
        kind = str(item.get("provenance_kind", ""))
        if kind not in PROVENANCE_KINDS:
            raise ValueError(f"mechanism {method_id} has unsupported provenance kind {kind!r}")
        reference_keys = tuple(str(key) for key in item.get("reference_keys", ()))
        usage_keys = tuple(
            str(key) for key in item.get("baseline_usage_reference_keys", ())
        )
        for key in (*reference_keys, *usage_keys):
            if key not in references:
                raise ValueError(f"mechanism {method_id} has unknown reference {key!r}")
        if not reference_keys:
            raise ValueError(f"mechanism {method_id} requires a primary reference")
        algorithm_location = str(item.get("algorithm_location", "")).strip()
        if not algorithm_location:
            raise ValueError(f"mechanism {method_id} requires algorithm_location")
        usage = tuple(references[key] for key in usage_keys)
        if kind == "common_baseline":
            paper_count = len({ref.reference_id for ref in usage if ref.kind == "paper"})
            has_benchmark = any(ref.kind == "benchmark" for ref in usage)
            if paper_count < 2 and not has_benchmark:
                raise ValueError(
                    f"common baseline {method_id} requires two papers or an established benchmark"
                )
        mechanisms[method_id] = MechanismRecord(
            method_id=method_id,
            family_id=str(item.get("family_id", method_id)),
            track=str(item["track"]),
            implementation_kind=str(item["implementation_kind"]),
            provenance_kind=kind,
            reference_keys=reference_keys,
            baseline_usage_reference_keys=usage_keys,
            algorithm_location=algorithm_location,
            supported_case_types=frozenset(
                str(value) for value in item.get("supported_case_types", ())
            ),
            source=str(item.get("source", "")),
            deviations=tuple(str(value) for value in item.get("deviations", ())),
            references=tuple(references[key] for key in reference_keys),
            baseline_usage_references=usage,
        )
    return ProvenanceCatalog(references=references, mechanisms=mechanisms)


def validate_provenance(
    registry: MethodRegistry, catalog: ProvenanceCatalog
) -> None:
    registered = {spec.method_id for spec in registry.specs()}
    cataloged = set(catalog.mechanisms)
    if registered != cataloged:
        missing_catalog = sorted(registered - cataloged)
        missing_registry = sorted(cataloged - registered)
        raise ValueError(
            f"registry/catalog mismatch: registry_only={missing_catalog}, "
            f"catalog_only={missing_registry}"
        )
    for spec in registry.specs():
        record = catalog.mechanisms[spec.method_id]
        if spec.track != record.track or spec.family_id != record.family_id:
            raise ValueError(f"registry/catalog identity mismatch for {spec.method_id}")
        if spec.implementation_kind != record.implementation_kind:
            raise ValueError(f"registry/catalog implementation mismatch for {spec.method_id}")
        if spec.supported_case_types != record.supported_case_types:
            raise ValueError(f"registry/catalog setting mismatch for {spec.method_id}")


def coverage_by_kind(
    catalog: ProvenanceCatalog,
    track: str,
    case_type: str | None = None,
) -> dict[str, Any]:
    records = [
        record
        for record in catalog.mechanisms.values()
        if record.track == track
        and (case_type is None or case_type in record.supported_case_types)
    ]
    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.provenance_kind] = by_kind.get(record.provenance_kind, 0) + 1
    literature_families = {
        record.family_id
        for record in records
        if record.provenance_kind in LITERATURE_KINDS
    }
    return {
        "method_count": len(records),
        "family_count": len({record.family_id for record in records}),
        "independent_literature_family_count": len(literature_families),
        "by_kind": dict(sorted(by_kind.items())),
    }


__all__ = [
    "DEFAULT_MECHANISMS",
    "DEFAULT_REFERENCES",
    "MechanismRecord",
    "ProvenanceCatalog",
    "ReferenceRecord",
    "coverage_by_kind",
    "load_provenance",
    "validate_provenance",
]
