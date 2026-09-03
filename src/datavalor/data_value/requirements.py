"""Normalize portable requirement payloads into DataValor request context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_requirements(path: str | Path) -> dict[str, Any]:
    target = Path(path); suffix = target.suffix.lower()
    if suffix in {".json", ".jsonl", ".ndjson"}:
        if suffix == ".json": payload = json.loads(target.read_text(encoding="utf-8"))
        else: payload = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif suffix in {".yaml", ".yml"}:
        import yaml
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported requirements format {suffix!r}")
    if isinstance(payload, dict) and "requirements" in payload: payload = payload["requirements"]
    if isinstance(payload, dict) and any(key in payload for key in ("users", "tasks", "preferences", "rights_bundle", "cost_context")):
        result = {key: payload.get(key, [] if key in {"users", "tasks", "preferences"} else {}) for key in ("users", "tasks", "preferences", "rights_bundle", "cost_context")}
        return result
    rows = payload if isinstance(payload, list) else [payload]
    result = {"users": [], "tasks": [], "preferences": [], "rights_bundle": {}, "cost_context": {}}
    for row in rows:
        if not isinstance(row, dict): raise ValueError("Requirement records must be objects")
        kind = str(row.get("record_type", row.get("entity_type", ""))).lower()
        if kind in {"user", "buyer"} or ("user_id" in row and "task_id" not in row): result["users"].append({k: v for k, v in row.items() if k not in {"record_type", "entity_type"}})
        elif kind == "task" or "task_id" in row: result["tasks"].append({k: v for k, v in row.items() if k not in {"record_type", "entity_type"}})
        elif kind in {"preference", "rating"}: result["preferences"].append({k: v for k, v in row.items() if k not in {"record_type", "entity_type"}})
        elif kind in {"rights", "rights_bundle"}: result["rights_bundle"].update(row)
        elif kind in {"cost", "cost_context"}: result["cost_context"].update(row)
        else: raise ValueError(f"Cannot classify requirement record: {sorted(row)}")
    return result


def merge_requirement_bundles(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = {key: list(value) if isinstance(value, list) else dict(value) if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, list): result.setdefault(key, []).extend(value)
        elif isinstance(value, dict): result.setdefault(key, {}).update(value)
        else: result[key] = value
    return result


__all__ = ["load_requirements", "merge_requirement_bundles"]
