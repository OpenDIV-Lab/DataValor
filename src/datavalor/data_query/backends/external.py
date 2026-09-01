"""DB-GPT and Vanna adapters for DataValor query planning/execution.

Both projects expose different combinations of SDK, service and database
methods.  DataValor therefore accepts an injected client/transport and resolves
common public methods only at execution time.  External SQL/agent response
objects are immediately normalized into DataValor plan/result models.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from datavalor.core import ComponentSpec, RunContext, require_capability

from ..interfaces import QueryExecutor, QueryPlanner
from ..models import (
    QueryAuthorization,
    QueryPlan,
    QueryPlanStep,
    QueryRequest,
    QueryResult,
    QueryTraceEvent,
)
from ._utils import as_mapping, columns, records


class ExternalQueryPlanner(QueryPlanner):
    backend = "external"
    capability = "external"
    distribution = "external"
    module = "external"
    extra = "query"

    def __init__(self, *, generator: Callable[..., Any] | None = None, client: Any = None,
                 method: str | None = None, timeout: float = 30.0) -> None:
        self.generator, self.client, self.method, self.timeout = generator, client, method, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(f"{self.backend}.planner", "0.1.0", "data_query", "query_planner",
                             capabilities=("text_to_sql", "query_plan"), requires=(self.distribution + ">=0.1",))

    def _generate(self, request: QueryRequest, authorization: QueryAuthorization) -> Any:
        fn = self.generator
        if fn is None and self.client is not None:
            fn = getattr(self.client, self.method or "generate_sql", None)
            if fn is None:
                fn = getattr(self.client, "ask", None) or getattr(self.client, "generate", None)
        if fn is None:
            module = require_capability(self.capability, self.module, distribution=self.distribution, extra=self.extra)
            fn = getattr(module, self.method or "generate_sql", None) or getattr(module, "ask", None)
        if not callable(fn):
            raise RuntimeError(f"{self.backend} exposes no query generation method")
        try:
            return fn(question=request.question, products=authorization.approved_products,
                      parameters=request.parameters, timeout=self.timeout)
        except TypeError:
            return fn(request.question)

    def plan(self, request: QueryRequest, authorization: QueryAuthorization, context: RunContext) -> QueryPlan:
        if authorization.decision.value != "allow":
            return QueryPlan(request.request_id, (), authorization, f"{self.backend}.planner",
                             diagnostics={"blocked": True, "run_id": context.run_id})
        raw = self._generate(request, authorization)
        mapping = as_mapping(raw)
        sql = mapping.get("sql", mapping.get("query", mapping.get("statement")))
        if sql is None and isinstance(raw, str):
            sql = raw
        if not sql:
            raise ValueError(f"{self.backend} returned no SQL statement")
        step = QueryPlanStep("step-0", "sql", authorization.approved_products, str(sql),
                             parameters=dict(mapping.get("parameters", request.parameters)))
        return QueryPlan(request.request_id, (step,), authorization, f"{self.backend}.planner",
                         diagnostics={"backend": self.backend, "run_id": context.run_id, "raw_keys": tuple(mapping.keys())})


class DBGPTQueryPlanner(ExternalQueryPlanner):
    backend, capability, distribution, module, extra = "db_gpt", "db_gpt", "dbgpt", "dbgpt", "query"


class VannaQueryPlanner(ExternalQueryPlanner):
    backend, capability, distribution, module, extra = "vanna", "vanna", "vanna", "vanna", "query"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("method", "generate_sql")
        super().__init__(**kwargs)


class ExternalQueryExecutor(QueryExecutor):
    def __init__(self, *, executor: Callable[..., Any] | None = None, client: Any = None,
                 timeout: float = 60.0, backend: str = "external") -> None:
        self.executor, self.client, self.timeout, self.backend = executor, client, timeout, backend

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(f"{self.backend}.executor", "0.1.0", "data_query", "query_executor",
                             capabilities=("query_execution",), requires=())

    def execute(self, plan: QueryPlan, context: RunContext) -> QueryResult:
        if plan.authorization.decision.value != "allow":
            return QueryResult(plan.request_id, trace=(QueryTraceEvent("execution", "blocked", {"decision": plan.authorization.decision.value}),))
        fn = self.executor
        if fn is None and self.client is not None:
            fn = getattr(self.client, "run_sql", None) or getattr(self.client, "execute", None) or getattr(self.client, "query", None)
        if fn is None:
            raise RuntimeError("ExternalQueryExecutor requires executor or client")
        statements = tuple(step.statement for step in plan.steps if step.statement)
        try:
            raw = fn(statements=statements, plan=plan, context=context, timeout=self.timeout)
        except TypeError:
            raw = fn(statements[0] if len(statements) == 1 else statements)
        mapping = as_mapping(raw)
        rows = records(mapping if mapping else raw)
        answer = mapping.get("answer", mapping.get("text"))
        return QueryResult(plan.request_id, str(answer) if answer is not None else None, rows, columns(rows),
                           trace=(QueryTraceEvent("execution", "completed", {"backend": self.backend, "row_count": len(rows)}),),
                           diagnostics={"backend": self.backend, "run_id": context.run_id})


__all__ = ["DBGPTQueryPlanner", "ExternalQueryExecutor", "VannaQueryPlanner"]
