"""Machine-readable mechanism provenance and coverage summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .registry import MethodRegistry
from .resources import resource_path

DEFAULT_CATALOG = resource_path("catalog", "mechanisms.yaml")


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = raw.get("mechanisms", raw)
    result: dict[str, dict[str, Any]] = {}
    for item in entries:
        entry = dict(item)
        method_id = str(entry["method_id"])
        if method_id in result:
            raise ValueError(f"duplicate catalog method_id: {method_id}")
        result[method_id] = entry
    return result


def catalog_summary(
    registry: MethodRegistry,
    cases: Mapping[str, tuple[Any, ...]],
) -> dict[str, Any]:
    tracks: dict[str, Any] = {}
    for track in ("valuation", "procurement", "trading"):
        specs = registry.specs(track)
        families = {spec.family_id for spec in specs}
        native_families = {
            spec.family_id for spec in specs if spec.implementation_kind == "native"
        }
        case_types = sorted({case.case_type for case in cases.get(track, ())})
        tracks[track] = {
            "method_count": len(specs),
            "family_count": len(families),
            "native_family_count": len(native_families),
            "settings": {
                case_type: {
                    "method_count": len(registry.compatible(track, case_type)),
                    "family_count": len(
                        {
                            spec.family_id
                            for spec in registry.compatible(track, case_type)
                            if spec.implementation_kind == "native"
                        }
                    ),
                }
                for case_type in case_types
            },
        }
    return {"tracks": tracks}


__all__ = ["DEFAULT_CATALOG", "catalog_summary", "load_catalog"]
