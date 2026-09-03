"""Dependency-free descriptive profilers for ordinary tabular data."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext

from .interfaces import DataProfiler, ProfileComparator, ProfileMetric
from .models import (
    DatasetProfile,
    FieldProfile,
    ProfileComparison,
    ProfileDifference,
    ProfileRequest,
)


def records_for(product: DataProduct, request: ProfileRequest) -> list[dict[str, Any]]:
    supplied = request.options.get("records")
    if supplied is not None:
        rows = [dict(row) for row in supplied]
    else:
        from datavalor.data_gov.data_product import adapter_from_uri

        rows = [dict(row) for row in adapter_from_uri(product.data.uri).records()]
    if request.sample_size is None:
        return rows
    # A non-positive sample is an explicit request for an empty profile; avoid
    # Python's negative slicing semantics (which would silently drop rows).
    return rows[: max(0, request.sample_size)]


def _type_of(values: Iterable[Any]) -> str:
    values = [value for value in values if value is not None]
    if not values:
        return "unknown"
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    if all(isinstance(value, str) for value in values):
        return "string"
    return "mixed"


def _numeric(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))]


class BasicProfileMetric(ProfileMetric):
    """Measure one field or dataset using only Python standard-library types."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.profile_metric", "1.0.0", "data_prof", "profile_metric", capabilities=("tabular", "descriptive"))

    def measure(self, product: DataProduct, field: str | None, context: RunContext):
        supplied = context.config.get("records")
        if supplied is not None:
            rows = [dict(row) for row in supplied]
        else:
            rows = [dict(row) for row in __import__("datavalor.data_gov.data_product", fromlist=["adapter_from_uri"]).adapter_from_uri(product.data.uri).records()]
        if field is None:
            return {"record_count": len(rows), "field_count": len({key for row in rows for key in row})}
        values = [row.get(field) for row in rows]
        present = [value for value in values if value is not None]
        return {"field": field, "count": len(values), "missing_count": len(values) - len(present), "distinct_count": len({str(value) for value in present}), "inferred_type": _type_of(values)}


class BasicDataProfiler(DataProfiler):
    """Build field-level profile facts, distributions and numeric summaries."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.data_profiler", "1.0.0", "data_prof", "profiler", capabilities=("tabular", "numeric", "categorical"))

    def profile(self, product: DataProduct, request: ProfileRequest, context: RunContext) -> DatasetProfile:
        rows = records_for(product, request)
        names = list(request.fields) if request.fields else sorted({str(key) for row in rows for key in row})
        fields: list[FieldProfile] = []
        for name in names:
            values = [row.get(name) for row in rows]
            present = [value for value in values if value is not None]
            numeric = _numeric(present)
            stats: dict[str, Any] = {}
            distribution: dict[str, Any] = {}
            if numeric:
                stats.update(min=min(numeric), max=max(numeric), mean=sum(numeric) / len(numeric), sum=sum(numeric))
            elif present:
                counts = Counter(str(value) for value in present)
                distribution = {key: count / len(present) for key, count in counts.most_common(20)}
            fields.append(FieldProfile(name, _type_of(values), len(values), len(values) - len(present), len({str(value) for value in present}), stats, distribution, (Evidence("profile.field", summary=f"字段 {name} 的本地画像", metadata={"run_id": context.run_id}),)))
        return DatasetProfile(product.product_id, len(rows), len(fields), tuple(fields), properties={"sampled": request.sample_size is not None, "sample_size": request.sample_size, "field_names": tuple(names)}, diagnostics={"run_id": context.run_id, "backend": self.spec.name})


class BasicProfileComparator(ProfileComparator):
    """Compare profile facts and report only descriptive changes."""

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("basic.profile_comparator", "1.0.0", "data_prof", "profile_comparator", capabilities=("dataset", "field"))

    def compare(self, reference: DatasetProfile, current: DatasetProfile, context: RunContext) -> ProfileComparison:
        differences: list[ProfileDifference] = []
        if reference.record_count != current.record_count:
            differences.append(ProfileDifference("record_count", reference.record_count, current.record_count, float(current.record_count or 0) - float(reference.record_count or 0)))
        old = {field.name: field for field in reference.fields}
        new = {field.name: field for field in current.fields}
        for name in sorted(set(old) | set(new)):
            if name not in old or name not in new:
                differences.append(ProfileDifference(f"fields.{name}", old.get(name), new.get(name), details={"change": "added" if name in new else "removed"}))
                continue
            if old[name].missing_count != new[name].missing_count:
                differences.append(ProfileDifference(f"fields.{name}.missing_count", old[name].missing_count, new[name].missing_count, float(new[name].missing_count or 0) - float(old[name].missing_count or 0)))
            if old[name].distinct_count != new[name].distinct_count:
                differences.append(ProfileDifference(f"fields.{name}.distinct_count", old[name].distinct_count, new[name].distinct_count, float(new[name].distinct_count or 0) - float(old[name].distinct_count or 0)))
        return ProfileComparison(reference.product_id, current.product_id, tuple(differences), summary={"difference_count": len(differences)}, diagnostics={"run_id": context.run_id})


__all__ = ["BasicDataProfiler", "BasicProfileComparator", "BasicProfileMetric", "records_for"]
