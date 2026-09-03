"""DataValor-native authorization, result guarding and agent orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import ComponentSpec, Evidence, RunContext

from ..interfaces import DataAgent, QueryAuthorizer, ResultGuard
from ..models import (
    AuthorizationDecision,
    QueryAuthorization,
    QueryRequest,
    QueryResult,
    QueryTraceEvent,
)
from ._utils import columns


class RightsQueryAuthorizer(QueryAuthorizer):
    """Authorize queries using product rights and an optional policy callback."""

    def __init__(self, policy: Callable[..., Any] | None = None, *, purpose: str = "query") -> None:
        self.policy, self.purpose = policy, purpose

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("rights.query_authorizer", "0.1.0", "data_query", "query_authorizer",
                             capabilities=("rights_check", "purpose_check"))

    def authorize(self, request: QueryRequest, context: RunContext) -> QueryAuthorization:
        if not request.products:
            return QueryAuthorization(request.request_id, AuthorizationDecision.DENY,
                                      policies=("product_required",), diagnostics={"run_id": context.run_id})
        approved: list[str] = []
        denied: list[str] = []
        for product in request.products:
            purposes = product.rights.purposes
            if purposes and self.purpose not in purposes and (request.task is None or request.task.objective not in purposes):
                denied.append(product.product_id)
            else:
                approved.append(product.product_id)
        decision = AuthorizationDecision.ALLOW if approved and not denied else AuthorizationDecision.REVIEW if approved else AuthorizationDecision.DENY
        details: dict[str, Any] = {"run_id": context.run_id, "denied_products": tuple(denied)}
        if self.policy is not None:
            result = self.policy(request=request, approved_products=tuple(approved), context=context)
            if isinstance(result, Mapping):
                details.update(result)
                decision = AuthorizationDecision(str(result.get("decision", decision.value)))
            elif result is False:
                decision = AuthorizationDecision.DENY
        evidence = tuple(Evidence("rights.query", summary=f"product {pid} query purpose check") for pid in denied)
        return QueryAuthorization(request.request_id, decision, tuple(approved), ("rights", self.purpose),
                                  restrictions={"redact_fields": tuple(context.config.get("redact_fields", ())),
                                                "max_rows": context.config.get("max_rows")},
                                  evidence=evidence, diagnostics=details)


class QueryResultGuard(ResultGuard):
    """Apply deterministic row limits, field redaction and optional aggregation."""

    def __init__(self, *, redact_fields: tuple[str, ...] = (), max_rows: int | None = None,
                 redaction: str = "[REDACTED]") -> None:
        self.redact_fields, self.max_rows, self.redaction = tuple(redact_fields), max_rows, redaction

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("default.result_guard", "0.1.0", "data_query", "result_guard",
                             capabilities=("row_limit", "redaction", "trace"))

    def guard(self, request: QueryRequest, authorization: QueryAuthorization, result: QueryResult, context: RunContext) -> QueryResult:
        configured = authorization.restrictions.get("redact_fields") or self.redact_fields
        fields = tuple(str(field) for field in configured or ())
        configured_limit = authorization.restrictions.get("max_rows")
        limit = request.max_rows if request.max_rows is not None else configured_limit if configured_limit is not None else self.max_rows
        rows = tuple({key: self.redaction if str(key) in fields else value for key, value in row.items()} for row in result.records)
        truncated = result.truncated
        if limit is not None:
            if limit < 0:
                raise ValueError("max_rows must be non-negative")
            truncated = truncated or len(rows) > int(limit)
            rows = rows[: int(limit)]
        changes = {"redacted_fields": fields, "max_rows": limit, "truncated": truncated}
        trace = result.trace + (QueryTraceEvent("guard", "completed", changes),)
        return QueryResult(result.request_id, result.answer, rows, columns(rows), result.artifacts, trace, truncated,
                           {**result.diagnostics, "guard": changes, "run_id": context.run_id})


class GovernedDataAgent(DataAgent):
    """Run authorization -> planning -> execution -> guarding as one workflow."""

    def __init__(self, authorizer: QueryAuthorizer, planner: Any, executor: Any, guard: ResultGuard | None = None) -> None:
        self.authorizer, self.planner, self.executor = authorizer, planner, executor
        self.guard = guard or QueryResultGuard()

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("governed.data_agent", "0.1.0", "data_query", "data_agent",
                             capabilities=("authorization_gate", "result_guard", "trace"))

    def run(self, request: QueryRequest, context: RunContext) -> QueryResult:
        authorization = self.authorizer.authorize(request, context)
        trace = (QueryTraceEvent("authorization", authorization.decision.value,
                                 {"approved_products": authorization.approved_products}, authorization.evidence),)
        if authorization.decision is not AuthorizationDecision.ALLOW:
            return QueryResult(request.request_id, trace=trace + (QueryTraceEvent("agent", "blocked", {}),),
                               diagnostics={"decision": authorization.decision.value, "run_id": context.run_id})
        plan = self.planner.plan(request, authorization, context)
        trace += (QueryTraceEvent("planning", "completed", {"planner": plan.planner, "steps": len(plan.steps)}),)
        result = self.executor.execute(plan, context)
        result = QueryResult(result.request_id, result.answer, result.records, result.columns, result.artifacts,
                             trace + result.trace, result.truncated, result.diagnostics)
        return self.guard.guard(request, authorization, result, context)


__all__ = ["GovernedDataAgent", "QueryResultGuard", "RightsQueryAuthorizer"]
