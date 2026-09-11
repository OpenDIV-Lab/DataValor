from datetime import datetime, timedelta, timezone

import pytest

from datavalor.core import (
    ArtifactEnvelope,
    ComponentSpec,
    DataProduct,
    DataReference,
    RightsBundle,
    RunContext,
    TaskContext,
)
from datavalor.data_eval import (
    DemandFitEvaluator,
    EvaluationConfidenceEstimator,
    EvaluationRequest,
    EvaluationThresholdGate,
)
from datavalor.data_gov import (
    ArtifactStalenessEvaluator,
    RightsCompatibilityEvaluator,
    RightsRestrictivenessScorer,
)
from datavalor.data_prof import (
    CoverageProfileMetric,
    CrossProductOverlapAnalyzer,
    FreshnessProfileMetric,
    JoinabilityMetric,
    RarityProfileMetric,
)


def _product(name="p", **metadata):
    return DataProduct(name, name, DataReference(f"memory://{name}", "json"), "owner", metadata=metadata)


def test_rights_restriction_and_required_compatibility():
    open_rights = RightsBundle(("analysis", "training"), True, True, jurisdictions=("CN", "SG"))
    restricted = RightsBundle(("analysis",), False, False, jurisdictions=("CN",))
    scorer = RightsRestrictivenessScorer()
    assert scorer.score(restricted).score > scorer.score(open_rights).score
    result = RightsCompatibilityEvaluator().evaluate(
        open_rights,
        restricted,
        required=RightsBundle(("training",), commercial_use=True),
    )
    assert not result.compatible
    assert set(result.conflicts) >= {
        "required_purpose_unavailable",
        "required_commercial_use_unavailable",
    }


def test_artifact_staleness_age_checksum_and_breaking_change():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    artifact = ArtifactEnvelope(
        "a",
        "evaluation",
        "1",
        ComponentSpec("producer", "1", "data_eval", "evaluator"),
        {"score": 1},
        diagnostics={"data_checksum": "old"},
        created_at=created,
    )
    evaluator = ArtifactStalenessEvaluator()
    age_only = evaluator.evaluate(
        artifact,
        evaluated_at=created + timedelta(days=2),
        max_age_seconds=86400,
    )
    assert age_only.status == "incremental_refresh" and age_only.reusable
    changed = evaluator.evaluate(artifact, current_checksum="new")
    assert changed.status == "obsolete" and not changed.reusable
    assert evaluator.evaluate(artifact, breaking_change=True).status == "obsolete"


def test_market_profiles_coverage_rarity_freshness_and_joinability():
    rows = [
        {"id": "a", "region": "east", "updated": "2026-09-10T00:00:00+00:00"},
        {"id": "b", "region": "east", "updated": "2026-09-01T00:00:00+00:00"},
        {"id": "b", "region": "west", "updated": None},
        {"id": None, "region": None, "updated": "invalid"},
    ]
    context = RunContext("profile", config={"records": rows, "observed_at": "2026-09-11T00:00:00+00:00"})
    product = _product()
    coverage = CoverageProfileMetric().measure(product, "id,region", context)
    assert coverage["statistics"]["id"]["coverage_ratio"] == 0.75
    rarity = RarityProfileMetric().measure(product, "region", context)
    assert rarity["statistics"]["rare_values"] == ("west",)
    freshness = FreshnessProfileMetric().measure(product, "updated", context)
    assert freshness["statistics"]["invalid_count"] == 2
    joinability = JoinabilityMetric().measure(product, "id", context)
    assert joinability["statistics"]["duplicate_key_count"] == 1


def test_cross_product_overlap_reports_incremental_coverage():
    context = RunContext(
        "overlap",
        config={
            "left_records": [{"id": 1}, {"id": 2}],
            "right_records": [{"id": 2}, {"id": 3}],
        },
    )
    result = CrossProductOverlapAnalyzer().analyze(_product("left"), _product("right"), context, ("id",))
    assert result["statistics"]["jaccard_overlap"] == pytest.approx(1 / 3)
    assert result["statistics"]["right_incremental_ratio"] == 0.5


def test_demand_fit_hard_soft_requirements_and_confidence():
    product = _product("candidate", region=("CN",), freshness_days=3, records=1200)
    request = EvaluationRequest(
        task=TaskContext("forecast", "forecasting"),
        options={
            "requirements": {
                "region": ("CN",),
                "freshness_days": {"max": 7},
                "records": {"min": 2000},
            },
            "hard_requirements": ("region",),
            "weights": {"records": 2},
        },
    )
    report = DemandFitEvaluator().evaluate(product, request, (), RunContext("fit"))
    assert report.summary["status"] == "conditional"
    assert 0 < report.summary["demand_fit_score"] < 1
    required_gate = EvaluationThresholdGate().evaluate(report, {"missing.metric": {"min": 0.8, "required": True}})
    assert required_gate["status"] == "failed"
    estimator = EvaluationConfidenceEstimator()
    low = estimator.estimate(report, sample_size=10, population_size=1000)
    high = estimator.estimate(report, sample_size=900, population_size=1000)
    assert high["confidence"] > low["confidence"]


def test_invalid_profile_and_confidence_inputs():
    with pytest.raises(ValueError):
        CoverageProfileMetric().measure(_product(), None, RunContext("empty", config={"records": []}))
    with pytest.raises(ValueError):
        RarityProfileMetric(0)
    with pytest.raises(ValueError):
        EvaluationConfidenceEstimator().estimate(
            DemandFitEvaluator().evaluate(_product(), EvaluationRequest(), (), RunContext("fit")),
            sample_size=-1,
        )
