"""Transport helpers for protocol connectors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from datavalor.core.exceptions import DataValorError


class MarketConnectorError(DataValorError):
    pass


def call_remote(method: Callable[..., Any], *args: Any, retries: int = 0, timeout: float | None = None, **kwargs: Any) -> Any:
    last: Exception | None = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            if timeout is None:
                return method(*args, **kwargs)
            try:
                return method(*args, timeout=timeout, **kwargs)
            except TypeError as exc:
                if "timeout" not in str(exc):
                    raise
                return method(*args, **kwargs)
        except Exception as exc:
            last = exc
            if attempt >= max(0, int(retries)):
                break
    raise MarketConnectorError("market connector operation failed") from last


def normalize_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    for name in ("to_dict", "as_dict", "dict"):
        method = getattr(value, name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return result
    return {}
