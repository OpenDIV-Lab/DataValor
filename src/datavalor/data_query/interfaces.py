"""Extension interfaces for governed query planning, execution, and agents."""

from __future__ import annotations

from abc import abstractmethod

from datavalor.core import BaseComponent, RunContext

from .models import QueryAuthorization, QueryPlan, QueryRequest, QueryResult


class QueryAuthorizer(BaseComponent):
    """Apply identity, purpose, product rights, and policy gates before execution."""

    @abstractmethod
    def authorize(self, request: QueryRequest, context: RunContext) -> QueryAuthorization:
        """Return allow, deny, or review with explicit restrictions."""


class QueryPlanner(BaseComponent):
    """Translate an authorized request into inspectable execution steps."""

    @abstractmethod
    def plan(
        self,
        request: QueryRequest,
        authorization: QueryAuthorization,
        context: RunContext,
    ) -> QueryPlan:
        """Produce a plan without executing it."""


class QueryExecutor(BaseComponent):
    """Execute an authorized plan against connectors or computation engines."""

    @abstractmethod
    def execute(self, plan: QueryPlan, context: RunContext) -> QueryResult:
        """Execute a plan and retain an auditable trace."""


class ResultGuard(BaseComponent):
    """Apply row limits, redaction, aggregation, and output policy after execution."""

    @abstractmethod
    def guard(
        self,
        request: QueryRequest,
        authorization: QueryAuthorization,
        result: QueryResult,
        context: RunContext,
    ) -> QueryResult:
        """Return a policy-compliant result without hiding applied changes."""


class DataAgent(BaseComponent):
    """Coordinate authorization, planning, execution, and guarded response generation."""

    @abstractmethod
    def run(self, request: QueryRequest, context: RunContext) -> QueryResult:
        """Run a governed data-agent workflow and return its complete trace."""

