"""PySyft transaction processor for owner-side delivery and settlement."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import ComponentSpec, RunContext, require_capability
from datavalor.data_market.interfaces import TransactionProcessor
from datavalor.data_market.models import TransactionRecord


class SyftTransactionProcessor(TransactionProcessor):
    def __init__(self, *, executor: Callable[..., Any] | None = None, client: Any = None,
                 retries: int = 0, timeout: float = 60.0) -> None:
        self.executor, self.client, self.retries, self.timeout = executor, client, retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pysyft.transaction", "0.1.0", "data_market", "transaction_processor",
                             capabilities=("owner_side_execution", "permissions"), requires=("syft>=0.8",))

    def execute(self, outcome, context: RunContext) -> TransactionRecord:
        executor = self.executor
        if executor is None:
            if self.client is not None:
                executor = getattr(self.client, "execute", None) or getattr(self.client, "run", None)
            if executor is None:
                syft = require_capability("pysyft", "syft", distribution="syft", extra="governance")
                executor = getattr(syft, "execute", None)
        if not callable(executor):
            raise RuntimeError("Syft transaction requires an injected executor/client.execute")
        result = executor(outcome=outcome, context=context)
        details = dict(result) if isinstance(result, Mapping) else {"result": result}
        status = str(details.pop("status", "succeeded"))
        return TransactionRecord(f"syft:{context.run_id}", outcome, status,
                                 diagnostics={"backend": "pysyft", "run_id": context.run_id, "external_result": details})


__all__ = ["SyftTransactionProcessor"]
