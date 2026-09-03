"""Adapter for the ydata/``fg-data-profiling`` style profile report."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, require_capability

from ..interfaces import DataProfiler
from ..models import DatasetProfile, FieldProfile, ProfileRequest


def _records(product: DataProduct, request: ProfileRequest) -> list[dict[str, Any]]:
    supplied = request.options.get("records")
    if supplied is not None:
        rows = [dict(row) for row in supplied]
    else:
        from datavalor.data_gov.data_product import adapter_from_uri
        rows = [dict(row) for row in adapter_from_uri(product.data.uri).records()]
    return rows[: request.sample_size] if request.sample_size else rows


class FgDataProfiler(DataProfiler):
    """Build DataValor profiles from ``ydata_profiling.ProfileReport`` output."""

    def __init__(self, *, builder: Callable[..., Any] | None = None, minimal: bool = True) -> None:
        self.builder, self.minimal = builder, minimal

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("fg_data_profiling.profile", "0.1.0", "data_prof", "profiler",
                             capabilities=("dataframe_profile", "field_statistics"),
                             requires=("ydata-profiling>=4.0",))

    def _build(self, rows: list[dict[str, Any]], request: ProfileRequest) -> Any:
        if self.builder is not None:
            return self.builder(rows, request=request)
        profile_mod = require_capability("fg_data_profiling", "ydata_profiling", distribution="ydata-profiling", extra="profiling")
        data = request.options.get("data")
        if data is None:
            try:
                pandas = require_capability("pandas", "pandas", distribution="pandas", extra="profiling")
                data = pandas.DataFrame(rows)
            except Exception as exc:
                raise RuntimeError("profile adapter needs pandas or options['data']") from exc
        report_cls = getattr(profile_mod, "ProfileReport", None)
        if report_cls is None:
            raise RuntimeError("ydata_profiling.ProfileReport is unavailable")
        return report_cls(data, minimal=self.minimal)

    @staticmethod
    def _summary(report: Any) -> Mapping[str, Any]:
        if isinstance(report, Mapping):
            return report
        for method in ("to_dict", "get_description"):
            fn = getattr(report, method, None)
            if callable(fn):
                try:
                    value = fn()
                except TypeError:
                    continue
                if isinstance(value, Mapping):
                    return value
        description = getattr(report, "description_set", None)
        if isinstance(description, Mapping):
            return description
        to_json = getattr(report, "to_json", None)
        if callable(to_json):
            try:
                value = json.loads(to_json())
                if isinstance(value, Mapping):
                    return value
            except (TypeError, ValueError):
                pass
        return {}

    def profile(self, product: DataProduct, request: ProfileRequest, context: RunContext) -> DatasetProfile:
        rows = _records(product, request)
        summary = self._summary(self._build(rows, request))
        variables = summary.get("variables", summary.get("columns", {}))
        fields: list[FieldProfile] = []
        if isinstance(variables, Mapping):
            for name, info in variables.items():
                if not isinstance(info, Mapping):
                    continue
                count = info.get("count", info.get("n"))
                missing = info.get("n_missing", info.get("missing"))
                distinct = info.get("n_unique", info.get("distinct"))
                fields.append(FieldProfile(str(name), str(info.get("type", "unknown")), count, missing, distinct,
                                           statistics={k: v for k, v in info.items() if k not in {"type", "count", "n", "n_missing", "missing", "n_unique", "distinct"}},
                                           evidence=(Evidence("profile.field", summary=f"字段 {name} 的外部画像", metadata=dict(info)),)))
        return DatasetProfile(product.product_id, len(rows), len(fields), tuple(fields),
                              properties={"backend": "fg_data_profiling", "raw_summary_keys": tuple(summary.keys())},
                              diagnostics={"run_id": context.run_id, "sampled": request.sample_size is not None})


YDataProfilingAdapter = FgDataProfiler
FgDataProfilingAdapter = FgDataProfiler

__all__ = ["FgDataProfiler", "FgDataProfilingAdapter", "YDataProfilingAdapter"]
