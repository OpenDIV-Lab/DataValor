"""Immutable, content-addressed coalition-game artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class CoalitionGameTable:
    """A complete utility table over all coalitions of a fixed owner set."""

    owner_ids: tuple[str, ...]
    values: Mapping[int, float]
    fidelity: str
    measured_seconds: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        owners = tuple(str(owner) for owner in self.owner_ids)
        if len(set(owners)) != len(owners):
            raise ValueError("owner IDs must be unique")
        expected = set(range(1 << len(owners)))
        copied = {int(mask): float(value) for mask, value in self.values.items()}
        if set(copied) != expected:
            raise ValueError("coalition table must be complete with masks 0..2**n-1")
        if any(not math.isfinite(value) for value in copied.values()):
            raise ValueError("coalition utilities must be finite")
        if not self.fidelity:
            raise ValueError("fidelity must be non-empty")
        if not math.isfinite(self.measured_seconds) or self.measured_seconds < 0:
            raise ValueError("measured_seconds must be finite and non-negative")
        object.__setattr__(self, "owner_ids", owners)
        object.__setattr__(self, "values", MappingProxyType(copied))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def content_hash(self) -> str:
        payload = {
            "owner_ids": self.owner_ids,
            "fidelity": self.fidelity,
            "values": [[mask, self.values[mask]] for mask in sorted(self.values)],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def mask(self, coalition: tuple[str, ...]) -> int:
        positions = {owner: index for index, owner in enumerate(self.owner_ids)}
        unknown = set(coalition) - set(positions)
        if unknown:
            raise KeyError(f"unknown owner IDs: {sorted(unknown)}")
        if len(set(coalition)) != len(coalition):
            raise ValueError("coalition owner IDs must be unique")
        result = 0
        for owner in coalition:
            result |= 1 << positions[owner]
        return result

    def value(self, coalition: tuple[str, ...]) -> float:
        return self.values[self.mask(tuple(coalition))]


__all__ = ["CoalitionGameTable"]
