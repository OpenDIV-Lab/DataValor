"""Deterministic owner partitions and resumable coalition-table construction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..coalition_games import CoalitionGameTable


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    modality: str
    dataset_hash: str
    n_owners: int
    partition: str
    imbalance_ratio: int
    split_seed: int

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def partition_indices(
    labels: np.ndarray,
    *,
    n_owners: int,
    scheme: str,
    imbalance_ratio: int,
    seed: int,
    domains: np.ndarray | None = None,
) -> dict[str, tuple[int, ...]]:
    labels = np.asarray(labels)
    if n_owners < 1 or len(labels) < n_owners:
        raise ValueError("n_owners must be positive and no larger than the dataset")
    if scheme not in {"iid", "label_skew", "quantity_skew", "domain"}:
        raise ValueError(f"unknown partition scheme: {scheme}")
    rng = np.random.default_rng(seed)
    buckets = [[] for _ in range(n_owners)]
    if scheme == "iid":
        for label in np.unique(labels):
            rows = np.flatnonzero(labels == label)
            rng.shuffle(rows)
            for offset, row in enumerate(rows):
                buckets[offset % n_owners].append(int(row))
    elif scheme == "label_skew":
        ordered = np.lexsort((rng.random(len(labels)), labels))
        for owner, rows in enumerate(np.array_split(ordered, n_owners)):
            buckets[owner].extend(int(row) for row in rows)
    elif scheme == "quantity_skew":
        ordered = rng.permutation(len(labels))
        weights = np.linspace(1.0, float(imbalance_ratio), n_owners)
        raw = weights / weights.sum() * len(labels)
        counts = np.floor(raw).astype(int)
        counts[: len(labels) - counts.sum()] += 1
        cursor = 0
        for owner, count in enumerate(counts):
            buckets[owner].extend(int(row) for row in ordered[cursor : cursor + count])
            cursor += count
    else:
        if domains is None or len(domains) != len(labels):
            raise ValueError("domain partitions require one domain per row")
        domain_values = {value: index for index, value in enumerate(np.unique(domains))}
        for row, value in enumerate(domains):
            buckets[domain_values[value] % n_owners].append(row)
        empty = [index for index, bucket in enumerate(buckets) if not bucket]
        for owner in empty:
            donor = max(range(n_owners), key=lambda index: len(buckets[index]))
            buckets[owner].append(buckets[donor].pop())
    return {f"o{owner}": tuple(sorted(rows)) for owner, rows in enumerate(buckets)}


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2))
    os.replace(temporary, path)


class CoalitionTableBuilder:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def _paths(self, manifest: DatasetManifest, fidelity: str) -> tuple[Path, Path]:
        root = self.cache_dir / manifest.content_hash / fidelity
        return root / "values.partial.json", root / ".complete.json"

    def load_complete(
        self, manifest: DatasetManifest, fidelity: str
    ) -> CoalitionGameTable | None:
        partial, marker = self._paths(manifest, fidelity)
        if not marker.exists() or not partial.exists():
            return None
        record = json.loads(marker.read_text())
        payload = json.loads(partial.read_text())
        if record.get("manifest_hash") != manifest.content_hash:
            return None
        values = {int(mask): float(value) for mask, value in payload["values"].items()}
        table = CoalitionGameTable(
            tuple(f"o{index}" for index in range(manifest.n_owners)),
            values,
            fidelity,
            measured_seconds=float(payload.get("measured_seconds", 0.0)),
            metadata={"manifest_hash": manifest.content_hash},
        )
        if table.content_hash != record.get("table_hash"):
            return None
        return table

    def build(
        self,
        manifest: DatasetManifest,
        fidelity: str,
        evaluator: Callable[[int], float],
    ) -> CoalitionGameTable:
        completed = self.load_complete(manifest, fidelity)
        if completed is not None:
            return completed
        partial, marker = self._paths(manifest, fidelity)
        payload = (
            json.loads(partial.read_text())
            if partial.exists()
            else {"manifest_hash": manifest.content_hash, "values": {}, "measured_seconds": 0.0}
        )
        if payload.get("manifest_hash") != manifest.content_hash:
            raise ValueError("partial cache manifest hash mismatch")
        values = payload["values"]
        started = time.perf_counter()
        for mask in range(1 << manifest.n_owners):
            key = str(mask)
            if key in values:
                continue
            value = float(evaluator(mask))
            if not math.isfinite(value):
                raise ValueError(f"non-finite coalition utility for mask {mask}")
            values[key] = value
            payload["measured_seconds"] += time.perf_counter() - started
            _atomic_json(partial, payload)
            started = time.perf_counter()
        table = CoalitionGameTable(
            tuple(f"o{index}" for index in range(manifest.n_owners)),
            {int(mask): value for mask, value in values.items()},
            fidelity,
            measured_seconds=float(payload["measured_seconds"]),
            metadata={"manifest_hash": manifest.content_hash},
        )
        _atomic_json(
            marker,
            {
                "manifest_hash": manifest.content_hash,
                "table_hash": table.content_hash,
                "coalitions": len(table.values),
            },
        )
        return table


__all__ = [
    "CoalitionTableBuilder",
    "DatasetManifest",
    "partition_indices",
]

# Public real-game interfaces are imported last because their manifest loader
# consumes ``partition_indices`` from this module.
from .real_coalitions import (  # noqa: E402
    CostCalibration,
    RealCoalitionRecord,
    RealCoalitionTables,
    build_real_coalition_tables,
    calibrate_fidelity_cost,
)

__all__ += [
    "CostCalibration",
    "RealCoalitionRecord",
    "RealCoalitionTables",
    "build_real_coalition_tables",
    "calibrate_fidelity_cost",
]

from .real_oracle import (  # noqa: E402
    CachedTrajectoryOracle,
    CachedTrajectoryRecord,
    make_real_trajectory_oracle,
)

__all__ += [
    "CachedTrajectoryOracle",
    "CachedTrajectoryRecord",
    "make_real_trajectory_oracle",
]
