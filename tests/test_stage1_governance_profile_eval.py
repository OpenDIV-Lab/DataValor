from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RightsBundle, RunContext
from datavalor.data_eval import (
    QUALITY_METRICS,
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    EvaluationRequest,
    FieldValidityMetric,
)
from datavalor.data_gov import (
    METADATA_EXTRACTORS,
    CatalogQuery,
    GovernanceDecision,
    InMemoryMetadataCatalog,
    LocalMetadataExtractor,
    RightsPolicyEvaluator,
    SensitiveFieldScanner,
)
from datavalor.data_prof import (
    PROFILE_METRICS,
    PROFILERS,
    BasicDataProfiler,
    BasicProfileComparator,
    ProfileRequest,
)


def _product(path: Path, *, rights: RightsBundle | None = None) -> DataProduct:
    return DataProduct("stage1-test", "Stage 1 test", DataReference(str(path), "jsonl"), "owner", rights=rights or RightsBundle(purposes=("quality_assessment",)))


def _write(path: Path) -> None:
    path.write_text('{"id":"1","email":"a@example.test","score":1}\n{"id":"1","email":null,"score":"bad"}\n', encoding="utf-8")


def test_metadata_catalog_policy_and_security(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    _write(path)
    product = _product(path)
    context = RunContext("stage1-test")
    metadata = LocalMetadataExtractor().inspect(product, context)
    assert metadata.properties["record_count"] == 2
    assert len(metadata.properties["sha256"]) == 64
    assert next(field for field in metadata.fields if field.name == "email").classification == "email"

    catalog = InMemoryMetadataCatalog()
    catalog.upsert(metadata, context)
    assert catalog.search(CatalogQuery(tags=()), context)[0].product_id == product.product_id
    assert len(SensitiveFieldScanner().scan(product, {}, context).findings) == 1
    denied = RightsPolicyEvaluator().evaluate(product, "model_training", metadata, context)
    assert denied.decision is GovernanceDecision.DENY

    expired = _product(path, rights=RightsBundle(purposes=("quality_assessment",), valid_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert RightsPolicyEvaluator().evaluate(expired, "quality_assessment", metadata, context).decision is GovernanceDecision.DENY
    review = _product(path, rights=RightsBundle())
    assert RightsPolicyEvaluator().evaluate(review, "quality_assessment", metadata, context).decision is GovernanceDecision.REVIEW
    assert isinstance(METADATA_EXTRACTORS.create("local.metadata_extractor"), LocalMetadataExtractor)

    # Classification filters are evaluated against the extracted field schema,
    # not merely the free-text metadata representation.
    assert catalog.search(CatalogQuery(classifications=("email",)), context)[0].product_id == product.product_id


def test_profile_metrics_comparison_and_quality_report(tmp_path: Path):
    path = tmp_path / "rows.jsonl"
    _write(path)
    product = _product(path)
    context = RunContext("stage1-test")
    profiler = BasicDataProfiler()
    profile = profiler.profile(product, ProfileRequest(), context)
    score = next(field for field in profile.fields if field.name == "score")
    assert score.inferred_type == "mixed"
    assert score.missing_count == 0
    revised = profiler.profile(product, ProfileRequest(options={"records": [{"id": "1", "email": "a@example.test", "score": 1}]}), context)
    assert BasicProfileComparator().compare(profile, revised, context).summary["difference_count"] >= 1
    assert profiler.profile(product, ProfileRequest(sample_size=-1, options={"records": [{"id": "1"}]}), context).record_count == 0

    request = EvaluationRequest(options={"records": [{"id": "1", "email": "a@example.test", "score": 1}, {"id": "1", "email": "a@example.test", "score": 1}, {"id": "2", "email": None, "score": "bad"}], "required_fields": ("id", "email", "score"), "field_types": {"score": "number"}})
    report = CompositeEvaluator().evaluate(product, request, (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()), context)
    assert report.summary == {"status": "succeeded", "metric_count": 3, "failure_count": 0}
    assert report.metrics[0].statistics["missing_cells"] == 1
    assert report.metrics[1].statistics["duplicate_count"] == 1
    assert report.metrics[2].statistics["invalid"] == 2
    assert report.metrics[2].statistics["checked"] == 12
    assert report.metrics[2].value == 10 / 12
    assert isinstance(PROFILERS.create("basic.data_profiler"), BasicDataProfiler)
    assert isinstance(PROFILE_METRICS.create("basic.profile_metric"), object)
    assert isinstance(QUALITY_METRICS.create("basic.completeness"), CompletenessMetric)
