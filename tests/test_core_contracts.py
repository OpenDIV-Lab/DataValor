from decimal import Decimal

import pytest

from datavalor.core import (
    ArtifactEnvelope,
    ArtifactStatus,
    ComponentSpec,
    DataProduct,
    DataReference,
    DataScope,
    DuplicateComponentError,
    Registry,
    RegistryFrozenError,
    RunContext,
)
from datavalor.data_eval import EvaluationRequest, MetricResult, QualityMetric, ScoreDirection


class ConstantMetric(QualityMetric):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            name="test.constant",
            version="1.0.0",
            module="data_eval",
            kind="quality_metric",
            capabilities=("dataset",),
        )

    def compute(
        self,
        product: DataProduct,
        request: EvaluationRequest,
        context: RunContext,
    ) -> MetricResult:
        return MetricResult(
            name=self.spec.name,
            dimension="test",
            scope=request.scope,
            value=1.0,
            direction=ScoreDirection.HIGHER_IS_BETTER,
            target_id=product.product_id,
            diagnostics={"run_id": context.run_id},
        )


def test_registry_registers_lazy_factories_and_can_be_frozen():
    registry = Registry[QualityMetric]("tests.metrics")
    spec = ConstantMetric().spec
    registry.register(spec, ConstantMetric)

    assert registry.names() == ("test.constant",)
    assert registry.get_spec("test.constant") == spec
    assert isinstance(registry.create("test.constant"), ConstantMetric)

    with pytest.raises(DuplicateComponentError):
        registry.register(spec, ConstantMetric)

    registry.freeze()
    assert registry.frozen
    with pytest.raises(RegistryFrozenError):
        registry.register(
            ComponentSpec("other", "1", "data_eval", "quality_metric"),
            ConstantMetric,
        )


def test_metric_and_artifact_keep_semantic_layers_explicit():
    product = DataProduct(
        product_id="demo",
        title="Demo",
        data=DataReference("memory://demo", "jsonl", record_count=1),
        owner_id="supplier",
    )
    context = RunContext(run_id="run-1", seed=7)
    metric = ConstantMetric().compute(product, EvaluationRequest(), context)
    artifact = ArtifactEnvelope(
        artifact_id="artifact-1",
        kind="evaluation_report",
        schema_version="datavalor.evaluation/v1alpha1",
        producer=ConstantMetric().spec,
        payload=metric,
    )

    assert artifact.status is ArtifactStatus.SUCCEEDED
    assert artifact.payload.scope is DataScope.DATASET
    assert artifact.payload.value == 1.0


def test_money_uses_decimal_at_pricing_boundary():
    from datavalor.data_price import Money

    assert Money(Decimal("0.10")).amount + Money(Decimal("0.20")).amount == Decimal("0.30")

