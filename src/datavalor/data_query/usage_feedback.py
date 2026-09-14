"""Usage aggregation and task-utility feedback over existing query models."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from datavalor.data_eval import TaskUtilityResult

from .models import QueryResult, UsageEvent


@dataclass(frozen=True)
class UsageAggregate:
    group: Mapping[str, str]
    event_count: int
    quantity: float
    records_returned: int
    compute_seconds: float
    privacy_budget: float
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class UsageAggregator:
    """Deduplicate and aggregate valid usage events by explicit dimensions."""

    def aggregate(self, events: Sequence[UsageEvent], group_by: Sequence[str] = ("product_id", "buyer_id", "operation")) -> tuple[UsageAggregate, ...]:
        seen = set(); duplicate_ids = set(); invalid_ids = set(); grouped: dict[tuple[str, ...], list[UsageEvent]] = defaultdict(list)
        for event in events:
            if event.event_id in seen:
                duplicate_ids.add(event.event_id); continue
            seen.add(event.event_id)
            values = (event.quantity, event.records_returned, event.compute_seconds or 0.0, event.privacy_budget or 0.0)
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in values):
                invalid_ids.add(event.event_id); continue
            key = tuple(str(getattr(event, name, event.metadata.get(name, "<missing>"))) for name in group_by)
            grouped[key].append(event)
        return tuple(UsageAggregate(dict(zip(group_by, key)), len(items), sum(item.quantity for item in items), sum(item.records_returned for item in items), sum(item.compute_seconds or 0.0 for item in items), sum(item.privacy_budget or 0.0 for item in items), {"event_ids": tuple(sorted(item.event_id for item in items)), "duplicate_event_ids": tuple(sorted(duplicate_ids)), "invalid_event_ids": tuple(sorted(invalid_ids))}) for key, items in sorted(grouped.items()))


class QueryUtilityFeedback:
    """Convert explicit query outcome signals into task-utility evidence."""

    def evaluate(self, result: QueryResult, event: UsageEvent, *, task_id: str, baseline: float | None = None, weights: Mapping[str, float] | None = None) -> TaskUtilityResult:
        weights = {"success": 0.4, "records": 0.2, "latency": 0.2, "satisfaction": 0.2, **dict(weights or {})}
        success = 0.0 if result.diagnostics.get("error") or not (result.answer or result.records) else 1.0
        expected_records = max(1.0, float(event.metadata.get("expected_records", max(1, event.records_returned))))
        record_score = min(1.0, event.records_returned / expected_records)
        target_seconds = max(1e-12, float(event.metadata.get("target_compute_seconds", max(1.0, event.compute_seconds or 0.0))))
        latency_score = max(0.0, min(1.0, 1.0 - (event.compute_seconds or 0.0) / target_seconds))
        satisfaction = max(0.0, min(1.0, float(event.metadata.get("satisfaction", 0.5))))
        signals = {"success": success, "records": record_score, "latency": latency_score, "satisfaction": satisfaction}
        denominator = sum(max(0.0, float(weights.get(name, 0.0))) for name in signals)
        utility = sum(signals[name] * max(0.0, float(weights.get(name, 0.0))) for name in signals) / denominator if denominator else 0.0
        return TaskUtilityResult(
            event.product_id,
            task_id,
            utility,
            "query_realized_utility",
            baseline=baseline,
            diagnostics={
                "event_id": event.event_id,
                "request_id": result.request_id,
                "signals": signals,
                "weights": weights,
                "truncated": result.truncated,
            },
        )


@dataclass(frozen=True)
class UsageAnomaly:
    event_id: str
    code: str
    severity: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


class UsageAnomalyDetector:
    """Detect invalid, duplicate, quota, and group-volume spike signals."""

    def detect(self, events: Sequence[UsageEvent], *, quantity_limits: Mapping[str, float] | None = None, privacy_limits: Mapping[str, float] | None = None, spike_factor: float = 3.0) -> tuple[UsageAnomaly, ...]:
        if spike_factor <= 0:
            raise ValueError("spike_factor must be positive")
        quantity_limits, privacy_limits = quantity_limits or {}, privacy_limits or {}; anomalies = []
        counts = Counter(event.event_id for event in events)
        for event_id, count in counts.items():
            if count > 1: anomalies.append(UsageAnomaly(event_id, "usage.duplicate_event", "high", {"count": count}))
        by_group: dict[tuple[str, str], list[UsageEvent]] = defaultdict(list)
        for event in events:
            values = {"quantity": event.quantity, "records_returned": event.records_returned, "compute_seconds": event.compute_seconds or 0.0, "privacy_budget": event.privacy_budget or 0.0}
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in values.values()):
                anomalies.append(UsageAnomaly(event.event_id, "usage.invalid_measurement", "high", values)); continue
            if event.quantity > quantity_limits.get(event.product_id, math.inf): anomalies.append(UsageAnomaly(event.event_id, "usage.quantity_limit", "medium", {"quantity": event.quantity, "limit": quantity_limits[event.product_id]}))
            if (event.privacy_budget or 0.0) > privacy_limits.get(event.buyer_id, math.inf): anomalies.append(UsageAnomaly(event.event_id, "usage.privacy_limit", "high", {"privacy_budget": event.privacy_budget, "limit": privacy_limits[event.buyer_id]}))
            by_group[(event.product_id, event.operation)].append(event)
        for key, items in by_group.items():
            quantities = sorted(float(item.quantity) for item in items)
            if len(quantities) < 3: continue
            reference = sum(quantities[:-1]) / (len(quantities) - 1)
            if reference > 0 and quantities[-1] > reference * spike_factor:
                event = max(items, key=lambda item: item.quantity)
                anomalies.append(UsageAnomaly(event.event_id, "usage.volume_spike", "low", {"group": key, "quantity": event.quantity, "reference_mean": reference, "spike_factor": spike_factor}))
        return tuple(anomalies)


__all__ = ["QueryUtilityFeedback", "UsageAggregate", "UsageAggregator", "UsageAnomaly", "UsageAnomalyDetector"]
