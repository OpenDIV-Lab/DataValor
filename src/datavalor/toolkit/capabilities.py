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
    {"name": "datahub", "module": "datahub.emitter.rest_emitter", "distribution": "acryl-datahub"},
    {"name": "datahub_mce_builder", "module": "datahub.emitter.mce_builder", "distribution": "acryl-datahub"},
    {"name": "datahub_mcp", "module": "datahub.emitter.mcp", "distribution": "acryl-datahub"},
    {"name": "openmetadata", "module": "metadata.ingestion.ometa.ometa_api", "distribution": "openmetadata-ingestion"},
    {"name": "pydeequ", "module": "pydeequ", "distribution": "pydeequ"},
    {"name": "syft", "module": "syft", "distribution": "syft"},
    {"name": "ocean_py", "module": "ocean_lib", "distribution": "ocean-lib"},
    {"name": "db_gpt", "module": "dbgpt", "distribution": "dbgpt"},
    {"name": "vanna", "module": "vanna", "distribution": "vanna"},
)


def probe_external_capabilities() -> tuple[CapabilityStatus, ...]:
    """Return availability of planned optional backends without importing them."""

    return probe_capabilities(DEFAULT_EXTERNAL_CAPABILITIES)


__all__ = ["DEFAULT_EXTERNAL_CAPABILITIES", "probe_external_capabilities"]
