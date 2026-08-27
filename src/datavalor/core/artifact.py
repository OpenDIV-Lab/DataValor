"""Versioned artifact envelopes connecting otherwise independent modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Mapping, TypeVar

from .component import ComponentSpec

PayloadT = TypeVar("PayloadT")


class ArtifactStatus(str, Enum):
    """Completion state of an artifact-producing operation."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True)
class Evidence:
    """Inspectable evidence supporting a finding, score, or decision."""

    kind: str
    uri: str | None = None
    summary: str = ""
    checksum: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to an artifact without loading its payload."""

    artifact_id: str
    kind: str
    schema_version: str
    uri: str | None = None
    checksum: str | None = None


@dataclass(frozen=True)
class ArtifactEnvelope(Generic[PayloadT]):
    """Standard envelope for versioned, attributable, lineage-aware results."""

    artifact_id: str
    kind: str
    schema_version: str
    producer: ComponentSpec
    payload: PayloadT
    status: ArtifactStatus = ArtifactStatus.SUCCEEDED
    parents: tuple[ArtifactRef, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

