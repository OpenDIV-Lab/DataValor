"""Typed, lazy component registry used by every module."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Generic, TypeVar

from .component import BaseComponent, ComponentSpec
from .exceptions import (
    ComponentNotFoundError,
    DuplicateComponentError,
    RegistryFrozenError,
)

ComponentT = TypeVar("ComponentT", bound=BaseComponent)
ComponentFactory = Callable[[], ComponentT]


class Registry(Generic[ComponentT]):
    """Register factories lazily so optional dependencies are not imported eagerly."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self._entries: dict[str, tuple[ComponentSpec, ComponentFactory[ComponentT]]] = {}
        self._frozen = False
        self._lock = RLock()

    def register(
        self,
        spec: ComponentSpec,
        factory: ComponentFactory[ComponentT],
        *,
        replace: bool = False,
    ) -> None:
        """Register a lazy factory under ``spec.name``."""

        with self._lock:
            if self._frozen:
                raise RegistryFrozenError(f"Registry {self.namespace!r} is frozen")
            if spec.name in self._entries and not replace:
                raise DuplicateComponentError(
                    f"Component {spec.name!r} is already registered in {self.namespace!r}"
                )
            self._entries[spec.name] = (spec, factory)

    def register_instance(self, component: ComponentT, *, replace: bool = False) -> None:
        """Register a pre-built component, primarily for tests and local extensions."""

        self.register(component.spec, lambda: component, replace=replace)

    def create(self, name: str) -> ComponentT:
        """Create or return the component produced by a registered factory."""

        with self._lock:
            try:
                _, factory = self._entries[name]
            except KeyError as exc:
                raise ComponentNotFoundError(
                    f"Component {name!r} is not registered in {self.namespace!r}"
                ) from exc
        return factory()

    def get_spec(self, name: str) -> ComponentSpec:
        """Read component metadata without instantiating the component."""

        with self._lock:
            try:
                spec, _ = self._entries[name]
            except KeyError as exc:
                raise ComponentNotFoundError(
                    f"Component {name!r} is not registered in {self.namespace!r}"
                ) from exc
            return spec

    def specs(self) -> tuple[ComponentSpec, ...]:
        """Return registered specifications in deterministic name order."""

        with self._lock:
            return tuple(self._entries[name][0] for name in sorted(self._entries))

    def names(self) -> tuple[str, ...]:
        """Return registered names in deterministic order."""

        with self._lock:
            return tuple(sorted(self._entries))

    def freeze(self) -> None:
        """Prevent later registration changes during a reproducible run."""

        with self._lock:
            self._frozen = True

    @property
    def frozen(self) -> bool:
        """Whether this registry rejects further mutation."""

        return self._frozen

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return isinstance(name, str) and name in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

