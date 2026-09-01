"""Offline E5 tests for governed query adapters."""

from datavalor.core import (
    ActorProfile,
    ActorRole,
    DataProduct,
    DataReference,
    RightsBundle,
    RunContext,
)
from datavalor.data_query import (
    AuthorizationDecision,
    QueryRequest,
)
from datavalor.data_query.backends import (
    DBGPTQueryPlanner,
    ExternalQueryExecutor,
    GovernedDataAgent,
    QueryResultGuard,
    RightsQueryAuthorizer,
    VannaQueryPlanner,
)


def product(purposes=("query",)):
    return DataProduct("p1", "demo", DataReference("memory://p1", "records"), "owner",
                       rights=RightsBundle(purposes=purposes))


def request(question="show records", max_rows=None):
    actor = ActorProfile("analyst", ActorRole.ANALYST)
    return QueryRequest("q1", actor, question, (product(),), max_rows=max_rows)


def test_rights_authorizer_denies_without_query_purpose():
    denied_request = QueryRequest("q2", request().actor, "q", (product(("train",)),))
    denied = RightsQueryAuthorizer().authorize(denied_request, RunContext("e5"))
    assert denied.decision is AuthorizationDecision.DENY
    assert denied.approved_products == ()


def test_dbgpt_and_vanna_planners_normalize_sql():
    for planner in (
        DBGPTQueryPlanner(generator=lambda **kwargs: {"sql": "select * from t", "parameters": {"limit": 2}}),
        VannaQueryPlanner(generator=lambda question: "SELECT 1"),
    ):
        auth = RightsQueryAuthorizer().authorize(request(), RunContext("e5"))
        plan = planner.plan(request(), auth, RunContext("e5"))
        assert plan.steps[0].statement.lower().startswith("select")
        assert plan.authorization.approved_products == ("p1",)


def test_governed_agent_runs_authorize_plan_execute_guard_in_order():
    events = []

    def generator(**kwargs):
        events.append("plan")
        return "select email, value from t"

    def execute(**kwargs):
        events.append("execute")
        return {"records": [{"email": "a@example.org", "value": 1}, {"email": "b@example.org", "value": 2}]}

    agent = GovernedDataAgent(
        RightsQueryAuthorizer(),
        DBGPTQueryPlanner(generator=generator),
        ExternalQueryExecutor(executor=execute),
        QueryResultGuard(redact_fields=("email",)),
    )
    result = agent.run(request(max_rows=1), RunContext("e5"))
    assert events == ["plan", "execute"]
    assert result.records == ({"email": "[REDACTED]", "value": 1},)
    assert result.truncated is True
    assert [event.stage for event in result.trace] == ["authorization", "planning", "execution", "guard"]


def test_vanna_or_dbgpt_execution_can_return_answer_and_rows():
    planner = DBGPTQueryPlanner(generator=lambda **kwargs: "select 1")
    auth = RightsQueryAuthorizer().authorize(request(), RunContext("e5"))
    plan = planner.plan(request(), auth, RunContext("e5"))
    result = ExternalQueryExecutor(executor=lambda **kwargs: {"answer": "ok", "data": [{"x": 1}]}).execute(plan, RunContext("e5"))
    assert result.answer == "ok"
    assert result.columns == ("x",)
