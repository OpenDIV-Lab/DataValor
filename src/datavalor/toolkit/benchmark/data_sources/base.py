"""Internal provider contract used by benchmark data sources."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DistributionBatch:
    records: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDistribution:
    name = "benchmark.data_source"

    def generate(self, *, rng: random.Random, context: dict[str, Any] | None = None) -> DistributionBatch:
        raise NotImplementedError

