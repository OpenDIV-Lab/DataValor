"""PySyft permission and owner-side execution adapter.

PySyft deployment topology varies substantially (Domain, Datasite, client and
service APIs).  The adapter therefore accepts a narrow ``checker``/``executor``
callable and only uses the SDK when explicitly configured, while preserving
DataValor's rights and governance decision models.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import (
    BaseComponent,
    ComponentSpec,
    DataProduct,
    Evidence,
    RunContext,
    require_capability,
)
from datavalor.data_gov.interfaces import PolicyEvaluator
from datavalor.data_gov.models import (
    GovernanceDecision,
    GovernanceFinding,
    GovernanceReport,
    Severity,
)


class SyftOwnerExecution(BaseComponent):
    def __init__(self, *, executor: Callable[..., Any] | None = None, client: Any = None,
                 retries: int = 0, timeout: float = 30.0) -> None:
        self.executor, self.client, self.retries, self.timeout = executor, client, retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pysyft.owner_execution", "0.1.0", "data_gov", "owner_execution",
                             capabilities=("owner_side_execution", "permissions"), requires=("syft>=0.8",))

    def execute(self, product: DataProduct, operation: str, context: RunContext) -> Mapping[str, Any]:
        executor = self.executor
        if executor is None:
            if self.client is not None:
                executor = getattr(self.client, "execute", None) or getattr(self.client, "run", None)
            if executor is None:
                require_capability("pysyft", "syft", distribution="syft", extra="governance")
                raise RuntimeError("configure an owner-side PySyft executor/client explicitly")
        result = executor(product=product, operation=operation, context=context)
        if isinstance(result, Mapping):
            return dict(result)
        return {"result": result}


class SyftPolicyEvaluator(PolicyEvaluator):
    def __init__(self, *, checker: Callable[..., Any] | None = None, client: Any = None) -> None:
        self.checker, self.client = checker, client

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("pysyft.policy", "0.1.0", "data_gov", "policy_evaluator",
                             capabilities=("permissions",), requires=("syft>=0.8",))

    def evaluate(self, product: DataProduct, operation: str, metadata: Any, context: RunContext) -> GovernanceReport:
        rights = context.rights or product.rights
        allowed = rights.purposes == () or operation in rights.purposes
        details: Mapping[str, Any] = {"operation": operation, "rights_purposes": rights.purposes}
        if self.checker is not None:
            checked = self.checker(product=product, operation=operation, metadata=metadata, context=context)
            allowed = bool(checked.get("allowed", checked)) if isinstance(checked, Mapping) else bool(checked)
            details = {**details, **(dict(checked) if isinstance(checked, Mapping) else {})}
        elif self.client is not None:
            checker = getattr(self.client, "check_permission", None) or getattr(self.client, "authorize", None)
            if callable(checker):
                checked = checker(product=product, operation=operation, metadata=metadata)
                allowed = bool(checked.get("allowed", checked)) if isinstance(checked, Mapping) else bool(checked)
                details = {**details, "client_check": True}
        elif self.client is None:
            # Rights-only evaluation remains useful offline; the SDK is needed
            # only when an owner-side checker/client is actually configured.
            details = {**details, "sdk_check": "not_configured"}
        if allowed:
            return GovernanceReport(product.product_id, GovernanceDecision.ALLOW, policies=(operation,),
                                    diagnostics={"backend": "pysyft", **details})
        finding = GovernanceFinding("pysyft.permission_denied", "access", Severity.HIGH,
                                    "PySyft owner-side policy denied the operation",
                                    evidence=(Evidence("pysyft.policy", summary="permission check", metadata=dict(details)),),
                                    details=dict(details))
        return GovernanceReport(product.product_id, GovernanceDecision.DENY, policies=(operation,), findings=(finding,),
                                diagnostics={"backend": "pysyft", **details})


__all__ = ["SyftOwnerExecution", "SyftPolicyEvaluator"]
