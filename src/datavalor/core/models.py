"""Dependency-free models exchanged by DataValor modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class ActorRole(str, Enum):
    """Roles recognized across governance, market, and query interfaces."""

    OWNER = "owner"
    SUPPLIER = "supplier"
    BUYER = "buyer"
    PLATFORM = "platform"
    ANALYST = "analyst"
    AGENT = "agent"


class DataScope(str, Enum):
    """Granularity of a data reference or valuation target."""

    SAMPLE = "sample"
    GROUP = "group"
    DATASET = "dataset"
    PRODUCT = "product"
    SOURCE = "source"
    WINDOW = "window"


@dataclass(frozen=True)
class DataReference:
    """A portable pointer to data; the core package does not open the URI."""

    uri: str
    format: str
    media_type: str | None = None
    checksum: str | None = None
    schema_ref: str | None = None
    record_count: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RightsBundle:
    """Machine-readable usage rights accompanying a data product or request."""

    purposes: tuple[str, ...] = ()
    commercial_use: bool | None = None
    redistribution: bool | None = None
    exclusivity: str | None = None
    valid_until: datetime | None = None
    jurisdictions: tuple[str, ...] = ()
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataProduct:
    """Governed unit that can be evaluated, valued, listed, priced, and queried."""

    product_id: str
    title: str
    data: DataReference
    owner_id: str
    version: str = "1"
    description: str = ""
    rights: RightsBundle = field(default_factory=RightsBundle)
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActorProfile:
    """Minimal participant profile shared without imposing a user database."""

    actor_id: str
    role: ActorRole
    budget: Decimal | None = None
    currency: str | None = None
    preferences: Mapping[str, Any] = field(default_factory=dict)
    constraints: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskContext:
    """Downstream task that conditions evaluation, valuation, or querying."""

    task_id: str
    objective: str
    target: str | None = None
    utility_metric: str | None = None
    constraints: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostContext:
    """Acquisition, preparation, adoption, and operation costs."""

    acquisition: Decimal | None = None
    preparation: Decimal | None = None
    adoption: Decimal | None = None
    operation: Decimal | None = None
    currency: str = "CNY"
    metadata: Mapping[str, Any] = field(default_factory=dict)

