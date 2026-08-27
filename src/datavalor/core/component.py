"""Common component metadata and extension protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ComponentSpec:
    """Stable metadata used for discovery, provenance, and capability checks."""

    name: str
    version: str
    module: str
    kind: str
    api_version: str = "datavalor.component/v1alpha1"
    capabilities: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    description: str = ""


@runtime_checkable
class Component(Protocol):
    """Structural protocol implemented by every registered component."""

    @property
    def spec(self) -> ComponentSpec:
        """Return immutable component metadata."""


class BaseComponent(ABC):
    """Nominal base class for built-in and class-based extension interfaces."""

    @property
    @abstractmethod
    def spec(self) -> ComponentSpec:
        """Return immutable component metadata."""

