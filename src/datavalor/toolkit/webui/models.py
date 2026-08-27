"""Framework-neutral view and application specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ActionSpec:
    """User action exposed by a view without binding to a web framework."""

    action_id: str
    label: str
    capability: str
    parameters_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ViewSpec:
    """Declarative view boundary for artifacts, forms, charts, or tables."""

    view_id: str
    title: str
    kind: str
    required_artifacts: tuple[str, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ViewModel:
    """Framework-neutral data rendered by a concrete Web UI adapter."""

    view_id: str
    data: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplicationSpec:
    """Collection of views, navigation, and application-level options."""

    app_id: str
    title: str
    views: tuple[ViewSpec, ...]
    options: Mapping[str, Any] = field(default_factory=dict)

