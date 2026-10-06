"""Provenance gate for the 2026 ASSS-A/B estimators."""

from __future__ import annotations

from .valuation_shapley import OptionalMethodUnavailable

ASSS_PROVENANCE = {
    method_id: {
        "doi": "10.1145/3802016",
        "status": "unavailable",
        "reason": "official_implementation_unavailable:asss",
    }
    for method_id in ("asss_a", "asss_b")
}


def evaluate_asss(method_id: str):
    """Refuse to substitute an unaudited adaptive sampler for ASSS."""
    try:
        record = ASSS_PROVENANCE[method_id]
    except KeyError as exc:
        raise KeyError(f"unknown ASSS variant: {method_id}") from exc
    raise OptionalMethodUnavailable(record["reason"])


__all__ = ["ASSS_PROVENANCE", "evaluate_asss"]
