"""Deequ/Spark validation result adapter.

Deequ is JVM/Spark based, so DataValor consumes a completed job result rather
than importing or running Spark in the core package.  A runner can be injected
for local jobs; the output is a versioned artifact plus governance findings.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core import (
    ArtifactEnvelope,
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

from ._connector import as_mapping, call_with_retry, mapping_value


def _severity(status: str) -> Severity:
    return Severity.HIGH if status.lower() in {"failure", "failed", "error"} else Severity.INFO


class DeequValidationAdapter(BaseComponent):
    def __init__(self, runner: Callable[..., Any] | None = None, *, retries: int = 0, timeout: float = 30.0) -> None:
        self.runner, self.retries, self.timeout = runner, retries, timeout

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("deequ.validation", "0.1.0", "data_gov", "validation_artifact",
                             capabilities=("spark_quality", "constraints"), requires=("pydeequ>=1.2",))

    def validate(self, product: DataProduct, checks: Any, context: RunContext) -> ArtifactEnvelope[Mapping[str, Any]]:
        if self.runner is None:
            require_capability("pydeequ", "pydeequ", distribution="pydeequ", extra="governance")
            raise RuntimeError("DeequValidationAdapter requires an injected Spark/Deequ job runner")
        raw = call_with_retry(self.runner, product=product, checks=checks, context=context,
                              retries=self.retries, timeout=self.timeout)
        result = as_mapping(raw)
        return ArtifactEnvelope(f"deequ:{product.product_id}:{context.run_id}", "governance.deequ_validation",
                                "datavalor.governance.validation/v1", self.spec, dict(result),
                                evidence=(Evidence("deequ.result", summary="Deequ Spark validation result", metadata=dict(result)),),
                                diagnostics={"backend": "deequ", "run_id": context.run_id, "timeout": self.timeout})


class DeequPolicyEvaluator(PolicyEvaluator):
    def __init__(self, runner: Callable[..., Any] | None = None, *, retries: int = 0, timeout: float = 30.0) -> None:
        self.adapter = DeequValidationAdapter(runner, retries=retries, timeout=timeout)

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec("deequ.policy", "0.1.0", "data_gov", "policy_evaluator",
                             capabilities=("spark_quality", "constraints"), requires=("pydeequ>=1.2",))

    def evaluate(self, product: DataProduct, operation: str, metadata: Any, context: RunContext) -> GovernanceReport:
        artifact = self.adapter.validate(product, metadata or (), context)
        checks = artifact.payload.get("checks", artifact.payload.get("constraint_results", ()))
        findings = []
        for check in checks if isinstance(checks, (list, tuple)) else ():
            item = as_mapping(check)
            status = str(mapping_value(item, "status", "constraint_status", default="Success"))
            if status.lower() not in {"success", "passed", "pass"}:
                findings.append(GovernanceFinding("deequ.constraint_failed", "data_quality", _severity(status),
                                                  str(mapping_value(item, "message", "constraint_message", default="Deequ constraint failed")),
                                                  evidence=(Evidence("deequ.constraint", metadata=dict(item)),), details=dict(item)))
        return GovernanceReport(product.product_id, GovernanceDecision.REVIEW if findings else GovernanceDecision.ALLOW,
                                policies=(operation,), findings=tuple(findings),
                                diagnostics={"backend": "deequ", "artifact_id": artifact.artifact_id, "run_id": context.run_id})


__all__ = ["DeequValidationAdapter", "DeequPolicyEvaluator"]
