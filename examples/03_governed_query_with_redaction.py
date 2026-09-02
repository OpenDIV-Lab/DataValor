"""演示查询前授权、查询规划、执行和结果防护的完整链路。

运行：PYTHONPATH=src python examples/03_governed_query_with_redaction.py
"""

from __future__ import annotations

import json

from datavalor.core import (
    ActorProfile,
    ActorRole,
    DataProduct,
    DataReference,
    RightsBundle,
    RunContext,
)
from datavalor.data_query import (
    ExternalQueryExecutor,
    GovernedDataAgent,
    QueryRequest,
    QueryResultGuard,
    RightsQueryAuthorizer,
    VannaQueryPlanner,
)

ROWS = (
    {"customer_id": "c-001", "email": "alice@example.test", "region": "华东", "score": 0.91},
    {"customer_id": "c-002", "email": "bob@example.test", "region": "华南", "score": 0.74},
    {"customer_id": "c-003", "email": "chen@example.test", "region": "华东", "score": 0.66},
)


class LocalQueryEngine:
    """示例中的内存执行器；生产环境可替换为 SQL warehouse 或隐私计算 executor。"""

    def __call__(self, statement, **_kwargs):
        if "华东" in statement:
            return {"records": [row for row in ROWS if row["region"] == "华东"], "answer": "华东客户 2 条"}
        return {"records": ROWS, "answer": f"共 {len(ROWS)} 条"}


def main() -> None:
    product = DataProduct(
        "crm-segment-v1", "CRM 客户分群（合成）", DataReference("memory://crm", "records", record_count=len(ROWS)), "crm-owner",
        rights=RightsBundle(purposes=("query",), commercial_use=False, constraints={"purpose": "analytics"}),
    )
    buyer = ActorProfile("analyst-01", ActorRole.ANALYST)
    context = RunContext("example-03", actor_id=buyer.actor_id, config={"max_rows": 2, "redact_fields": ("email",)})
    planner = VannaQueryPlanner(generator=lambda question, **_: {"sql": "SELECT customer_id, email, region, score FROM crm WHERE region = '华东'" if "华东" in question else "SELECT * FROM crm"})
    agent = GovernedDataAgent(
        RightsQueryAuthorizer(purpose="query"), planner,
        ExternalQueryExecutor(executor=LocalQueryEngine(), backend="local"),
        QueryResultGuard(redact_fields=("email",), max_rows=2),
    )
    allowed = agent.run(QueryRequest("q-allowed", buyer, "查询华东客户的评分", (product,), max_rows=2), context)
    denied = agent.run(QueryRequest("q-denied", buyer, "导出客户邮箱", (DataProduct("restricted", "受限数据", DataReference("memory://restricted", "records"), "crm-owner", rights=RightsBundle(purposes=("model_training",))),)), context)
    print(json.dumps({"allowed": {"answer": allowed.answer, "records": allowed.records, "truncated": allowed.truncated, "trace": [event.event for event in allowed.trace]}, "denied": {"answer": denied.answer, "records": denied.records, "diagnostics": denied.diagnostics, "trace": [event.event for event in denied.trace]}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
