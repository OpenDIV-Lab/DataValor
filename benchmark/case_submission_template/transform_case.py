"""Deterministic example transformation for an open case contribution.

The admission validator hashes but deliberately does not execute this file.
Maintainers review and integrate accepted transformations separately.
"""

from __future__ import annotations

from typing import Any, Mapping


def build_case(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Map an anonymous ask support to one additive-procurement case payload."""

    asks = tuple(float(value) for value in snapshot["normalized_listing_asks"])
    if len(asks) != 8 or any(value <= 0 for value in asks):
        raise ValueError("the example requires eight positive normalized asks")
    singleton_values = tuple(0.45 + 0.10 * index for index in range(len(asks)))
    return {
        "case_id": "OPEN-dadada-datarade-one-off-q8",
        "source_unit_id": str(snapshot["source_unit_id"]),
        "costs": asks,
        "singleton_values": singleton_values,
        "budget": 0.5 * sum(asks),
        "economic_semantic": "listing_ask",
    }


__all__ = ["build_case"]
