"""Optional dependency and capability discovery for DataValor adapters.

The core package never imports optional backends eagerly.  Adapters call
``require_capability`` at execution time and receive a structured
``CapabilityStatus`` or a DataValor ``CapabilityUnavailableError``.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from dataclasses import dataclass
from typing import Any, Iterable

from .exceptions import CapabilityUnavailableError


@dataclass(frozen=True)
class CapabilityStatus:
    """Result of probing one optional Python module."""

    name: str
    module: str
    available: bool
    version: str | None = None
    reason: str | None = None
    distribution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module,
            "available": self.available,
            "version": self.version,
            "reason": self.reason,
            "distribution": self.distribution,
        }


def probe_capability(
    name: str,
    module: str,
    *,
    distribution: str | None = None,
) -> CapabilityStatus:
    """Probe an importable module without importing it.

    ``find_spec`` may itself raise for malformed namespace packages; those
    failures are represented as an unavailable capability rather than leaking
    backend-specific exceptions from DataValor discovery.
    """

    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        return CapabilityStatus(name, module, False, reason=str(exc), distribution=distribution)
    version = None
    if available and distribution:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
    reason = None if available else f"module {module!r} is not installed"
    return CapabilityStatus(name, module, available, version, reason, distribution)


def probe_capabilities(specs: Iterable[dict[str, str]]) -> tuple[CapabilityStatus, ...]:
    """Probe a collection of ``name/module/distribution`` mappings."""

    return tuple(
        probe_capability(
            str(spec["name"]),
            str(spec["module"]),
            distribution=spec.get("distribution"),
        )
        for spec in specs
    )


def require_capability(
    name: str,
    module: str,
    *,
    distribution: str | None = None,
    extra: str | None = None,
):
    """Import an optional module at adapter execution time.

    A DataValor exception includes an installation hint and preserves the
    original import error as its cause.  Callers should not invoke this from
    module-level code.
    """

    status = probe_capability(name, module, distribution=distribution)
    if not status.available:
        hint = f" Install the optional extra {extra!r}." if extra else ""
        raise CapabilityUnavailableError(
            f"Capability {name!r} is unavailable: {status.reason or 'module not found'}.{hint}"
        )
    try:
        return importlib.import_module(module)
    except (ImportError, ModuleNotFoundError) as exc:
        hint = f" Install the optional extra {extra!r}." if extra else ""
        raise CapabilityUnavailableError(
            f"Capability {name!r} could not be imported from {module!r}.{hint}"
        ) from exc


__all__ = ["CapabilityStatus", "probe_capability", "probe_capabilities", "require_capability"]
