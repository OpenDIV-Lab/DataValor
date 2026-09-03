"""Small, dependency-free helpers shared by external evaluation adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from datavalor.core import DataProduct


def records_for(product: DataProduct, options: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Resolve records from request options or a DataValor data-product adapter."""

    options = options or {}
    supplied = options.get("records")
    if supplied is not None:
        return [dict(row) for row in supplied]
    from datavalor.data_gov.data_product import adapter_from_uri

    return [dict(row) for row in adapter_from_uri(product.data.uri).records()]


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Best-effort conversion of external result objects to a mapping."""

    if isinstance(value, Mapping):
        return value
    for method in ("as_dict", "to_dict", "to_json_dict", "dict"):
        fn = getattr(value, method, None)
        if callable(fn):
            try:
                converted = fn()
            except TypeError:
                converted = fn(orient="records")
            if isinstance(converted, Mapping):
                return converted
            if isinstance(converted, list):
                return {"rows": converted}
    return {"value": value}


def first_number(value: Any) -> float | None:
    """Extract a finite-ish scalar from numpy/pandas/python scalar values."""

    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def rows_from_external(value: Any) -> list[Mapping[str, Any]]:
    """Convert a DataFrame/list-like issue table without importing pandas."""

    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if hasattr(value, "to_dict"):
        fn = value.to_dict
        try:
            rows = fn(orient="records")
        except TypeError:
            rows = fn()
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, Mapping)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [row for row in value if isinstance(row, Mapping)]
    return []
