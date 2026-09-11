"""Descriptive profiles used by market-aware evaluation and valuation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec, DataProduct, RunContext, canonical_sha256

from .builtins import records_for
from .interfaces import ProfileMetric
from .models import ProfileRequest


def _rows(product: DataProduct, context: RunContext, key: str = "records") -> list[dict[str, Any]]:
    return records_for(product, ProfileRequest(options={"records": context.config.get(key, context.config.get("records"))}))


class CoverageProfileMetric(ProfileMetric):
    """Describe non-null and distinct coverage for one or more dimensions."""
    @property
    def spec(self): return ComponentSpec("market.coverage", "1.0.0", "data_prof", "profile_metric", capabilities=("coverage", "market"))
    def measure(self, product, field, context):
        fields = tuple(item.strip() for item in (field or "").split(",") if item.strip()) or tuple(context.config.get("coverage_fields", ()))
        if not fields: raise ValueError("coverage requires at least one field")
        rows = _rows(product, context); stats = {}
        for name in fields:
            values = [row.get(name) for row in rows]; present = [value for value in values if value is not None]
            stats[name] = {"present_count": len(present), "missing_count": len(values) - len(present), "coverage_ratio": len(present) / len(values) if values else 0.0, "distinct_count": len({canonical_sha256(value) for value in present})}
        return {"fields": fields, "count": len(rows), "statistics": stats, "diagnostics": {"run_id": context.run_id}}


class RarityProfileMetric(ProfileMetric):
    """Describe long-tail categories without interpreting rarity as value."""
    def __init__(self, max_frequency: int = 1):
        if max_frequency < 1: raise ValueError("max_frequency must be positive")
        self.max_frequency = max_frequency
    @property
    def spec(self): return ComponentSpec("market.rarity", "1.0.0", "data_prof", "profile_metric", capabilities=("rarity", "long_tail", "market"))
    def measure(self, product, field, context):
        if not field: raise ValueError("rarity requires a field")
        values = [str(row[field]) for row in _rows(product, context) if row.get(field) is not None]; counts = Counter(values)
        rare = sorted(value for value, count in counts.items() if count <= self.max_frequency); rare_records = sum(counts[value] for value in rare)
        return {"field": field, "count": len(values), "statistics": {"distinct_count": len(counts), "rare_value_count": len(rare), "rare_record_count": rare_records, "rare_record_ratio": rare_records / len(values) if values else 0.0, "max_frequency": self.max_frequency, "rare_values": tuple(rare[:100])}, "diagnostics": {"rare_values_truncated": len(rare) > 100}}


class FreshnessProfileMetric(ProfileMetric):
    """Describe record-age distribution relative to an explicit observation time."""
    @property
    def spec(self): return ComponentSpec("market.freshness", "1.0.0", "data_prof", "profile_metric", capabilities=("time", "freshness", "market"))
    def measure(self, product, field, context):
        if not field: raise ValueError("freshness requires a timestamp field")
        now = context.config.get("observed_at") or context.started_at
        if isinstance(now, str): now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if now.tzinfo is None: now = now.replace(tzinfo=timezone.utc)
        ages, invalid = [], 0
        for row in _rows(product, context):
            value = row.get(field)
            try:
                stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
                ages.append(max(0.0, (now - stamp).total_seconds()) / 86400.0)
            except (TypeError, ValueError): invalid += 1
        ordered = sorted(ages)
        def percentile(probability: float) -> float | None:
            if not ordered:
                return None
            return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * probability))]
        return {"field": field, "count": len(ages), "statistics": {"mean_age_days": sum(ages) / len(ages) if ages else None, "min_age_days": min(ages) if ages else None, "median_age_days": percentile(0.5), "p90_age_days": percentile(0.9), "max_age_days": max(ages) if ages else None, "invalid_count": invalid}, "diagnostics": {"observed_at": now.isoformat()}}


class JoinabilityMetric(ProfileMetric):
    """Describe key completeness and uniqueness inside one product."""
    @property
    def spec(self): return ComponentSpec("market.joinability", "1.0.0", "data_prof", "profile_metric", capabilities=("keys", "joinability", "market"))
    def measure(self, product, field, context):
        if not field: raise ValueError("joinability requires a key field")
        rows = _rows(product, context); values = [row.get(field) for row in rows]; present = [canonical_sha256(value) for value in values if value is not None]
        return {"field": field, "count": len(rows), "statistics": {"key_coverage_ratio": len(present) / len(rows) if rows else 0.0, "key_uniqueness_ratio": len(set(present)) / len(present) if present else 0.0, "duplicate_key_count": len(present) - len(set(present)), "missing_key_count": len(rows) - len(present)}, "diagnostics": {"run_id": context.run_id}}


class CrossProductOverlapAnalyzer:
    """Compare exact key or record overlap between two products."""
    def analyze(self, left: DataProduct, right: DataProduct, context: RunContext, fields: Sequence[str] = ()) -> Mapping[str, Any]:
        left_rows = _rows(left, context, "left_records"); right_rows = _rows(right, context, "right_records")
        def signatures(rows):
            return {canonical_sha256(tuple(row.get(field) for field in fields) if fields else row) for row in rows}
        a, b = signatures(left_rows), signatures(right_rows); overlap = a & b; union = a | b
        return {"left_product_id": left.product_id, "right_product_id": right.product_id, "fields": tuple(fields), "statistics": {"left_unique": len(a), "right_unique": len(b), "overlap_count": len(overlap), "jaccard_overlap": len(overlap) / len(union) if union else 0.0, "right_incremental_ratio": len(b - a) / len(b) if b else 0.0}, "diagnostics": {"run_id": context.run_id}}


__all__ = ["CoverageProfileMetric", "CrossProductOverlapAnalyzer", "FreshnessProfileMetric", "JoinabilityMetric", "RarityProfileMetric"]
