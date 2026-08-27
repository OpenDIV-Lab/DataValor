"""Models for statistical profiling and descriptive comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from datavalor.core import ArtifactRef, Evidence


@dataclass(frozen=True)
class ProfileRequest:
    """Select profiling depth, fields, sampling, and privacy behavior."""

    fields: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    sample_size: int | None = None
    include_examples: bool = False
    group_by: tuple[str, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldProfile:
    """Descriptive statistics and properties for one field."""

    name: str
    inferred_type: str
    count: int | None = None
    missing_count: int | None = None
    distinct_count: int | None = None
    statistics: Mapping[str, Any] = field(default_factory=dict)
    distribution: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class DatasetProfile:
    """Profile facts that remain distinct from quality judgments."""

    product_id: str
    record_count: int | None
    field_count: int | None
    fields: tuple[FieldProfile, ...]
    properties: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileDifference:
    """One descriptive change between two profiles."""

    path: str
    reference: Any
    current: Any
    delta: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileComparison:
    """Descriptive comparison; quality interpretation belongs to DataEval."""

    reference_product_id: str
    current_product_id: str
    differences: tuple[ProfileDifference, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

