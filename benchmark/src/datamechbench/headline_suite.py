"""Venue-independent contract for the frozen reference mechanism suite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HEADLINE_SUITE = PACKAGE_ROOT / "catalog" / "headline_suite.yaml"
TRACKS = ("valuation", "procurement", "trading")


@dataclass(frozen=True)
class HeadlineTrack:
    track: str
    setting_id: str
    structural_axis: str
    method_ids: tuple[str, ...]


@dataclass(frozen=True)
class HeadlineSuite:
    suite_id: str
    description: str
    flagships: Mapping[str, HeadlineTrack]

    @property
    def method_ids(self) -> tuple[str, ...]:
        return tuple(
            method_id
            for track in TRACKS
            for method_id in self.flagships[track].method_ids
        )


def _nonempty(raw: Any, label: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{label} must be non-empty")
    return value


def load_headline_suite(path: str | Path = DEFAULT_HEADLINE_SUITE) -> HeadlineSuite:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported headline-suite schema_version")
    records = raw.get("flagships")
    if not isinstance(records, Mapping) or set(records) != set(TRACKS):
        raise ValueError("headline suite must define valuation, procurement, and trading")
    flagships: dict[str, HeadlineTrack] = {}
    observed: set[str] = set()
    for track in TRACKS:
        record = records[track]
        if not isinstance(record, Mapping):
            raise ValueError(f"flagships.{track} must be a mapping")
        raw_methods = record.get("method_ids")
        if not isinstance(raw_methods, list) or not raw_methods:
            raise ValueError(f"flagships.{track}.method_ids must be a non-empty list")
        methods = tuple(_nonempty(item, f"flagships.{track}.method_ids") for item in raw_methods)
        if len(set(methods)) != len(methods):
            raise ValueError(f"flagships.{track}.method_ids contains duplicates")
        overlap = observed.intersection(methods)
        if overlap:
            raise ValueError(f"headline methods occur in multiple tracks: {sorted(overlap)}")
        observed.update(methods)
        flagships[track] = HeadlineTrack(
            track=track,
            setting_id=_nonempty(record.get("setting_id"), f"flagships.{track}.setting_id"),
            structural_axis=_nonempty(
                record.get("structural_axis"), f"flagships.{track}.structural_axis"
            ),
            method_ids=methods,
        )
    return HeadlineSuite(
        suite_id=_nonempty(raw.get("suite_id"), "suite_id"),
        description=_nonempty(raw.get("description"), "description"),
        flagships=flagships,
    )


__all__ = [
    "DEFAULT_HEADLINE_SUITE",
    "HeadlineSuite",
    "HeadlineTrack",
    "load_headline_suite",
]

