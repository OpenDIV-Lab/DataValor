"""Typed extension registries for DataQuery."""

from datavalor.core import Registry

from .interfaces import DataAgent, QueryAuthorizer, QueryExecutor, QueryPlanner, ResultGuard

QUERY_AUTHORIZERS = Registry[QueryAuthorizer]("data_query.authorizers")
QUERY_PLANNERS = Registry[QueryPlanner]("data_query.planners")
QUERY_EXECUTORS = Registry[QueryExecutor]("data_query.executors")
RESULT_GUARDS = Registry[ResultGuard]("data_query.result_guards")
DATA_AGENTS = Registry[DataAgent]("data_query.agents")

