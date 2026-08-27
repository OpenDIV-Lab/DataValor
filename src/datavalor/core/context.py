"""Execution context passed explicitly to algorithms and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import RightsBundle


@dataclass(frozen=True)
class RunContext:
    """Reproducibility, identity, rights, and configuration for one run."""

    run_id: str
    seed: int = 0
    actor_id: str | None = None
    task_id: str | None = None
    rights: RightsBundle | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

