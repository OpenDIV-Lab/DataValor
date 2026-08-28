"""Run metadata helpers with DataValor naming and no source-project dependency."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .io import file_sha256


def start_run(stage: str, config_path: str | Path | None = None, *, seed: int = 0) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "stage": str(stage),
        "run_id": str(uuid.uuid4()),
        "seed": int(seed),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "input_artifacts": [],
        "warnings": [],
        "_started_monotonic": time.monotonic(),
    }
    if config_path is not None:
        path = Path(config_path)
        metadata["config_path"] = str(path)
        if path.is_file():
            metadata["config_sha256"] = file_sha256(path)
    return metadata


def add_input_artifact(metadata: dict[str, Any], path: str | Path, *, role: str) -> None:
    target = Path(path)
    item: dict[str, Any] = {"role": str(role), "path": str(target)}
    if target.is_file():
        item["sha256"] = file_sha256(target)
        item["size_bytes"] = target.stat().st_size
    else:
        item["status"] = "missing"
    metadata.setdefault("input_artifacts", []).append(item)


def finish_run(metadata: dict[str, Any], *, warnings: Iterable[str] = ()) -> dict[str, Any]:
    started = float(metadata.pop("_started_monotonic", time.monotonic()))
    values = list(metadata.get("warnings", [])) + [str(item) for item in warnings if str(item).strip()]
    metadata["warnings"] = list(dict.fromkeys(values))
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    metadata["runtime_seconds"] = round(max(0.0, time.monotonic() - started), 6)
    return metadata
