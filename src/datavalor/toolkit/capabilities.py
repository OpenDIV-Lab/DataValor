"""Capability probes driven by the external-repository integration plan."""

from __future__ import annotations

from datavalor.core import CapabilityStatus, probe_capabilities

DEFAULT_EXTERNAL_CAPABILITIES = (
    {"name": "pydvl", "module": "pydvl", "distribution": "pydvl"},
    {"name": "opendataval", "module": "opendataval", "distribution": "opendataval"},
    {"name": "cleanlab", "module": "cleanlab", "distribution": "cleanlab"},
    {"name": "great_expectations", "module": "great_expectations", "distribution": "great-expectations"},
    {"name": "evidently", "module": "evidently", "distribution": "evidently"},
    {"name": "fg_data_profiling", "module": "ydata_profiling", "distribution": "ydata-profiling"},
    {"name": "torchmetrics", "module": "torchmetrics", "distribution": "torchmetrics"},
    {"name": "mesa", "module": "mesa", "distribution": "mesa"},
)


def probe_external_capabilities() -> tuple[CapabilityStatus, ...]:
    """Return availability of planned optional backends without importing them."""

    return probe_capabilities(DEFAULT_EXTERNAL_CAPABILITIES)


__all__ = ["DEFAULT_EXTERNAL_CAPABILITIES", "probe_external_capabilities"]
