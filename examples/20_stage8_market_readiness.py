"""Run the first market-readiness extension without optional dependencies."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from datavalor.core import (
    DataProduct,
    DataReference,
    RightsBundle,
    RunContext,
    TaskContext,
    write_json,
)
from datavalor.data_eval import DemandFitEvaluator, EvaluationConfidenceEstimator, EvaluationRequest
from datavalor.data_gov import RightsCompatibilityEvaluator, RightsRestrictivenessScorer
from datavalor.data_prof import (
    CoverageProfileMetric,
    CrossProductOverlapAnalyzer,
    FreshnessProfileMetric,
    JoinabilityMetric,
    RarityProfileMetric,
)


def main() -> None:
    rows = [
        {"id": "e-1", "region": "CN", "updated_at": "2026-09-10T00:00:00+00:00"},
        {"id": "e-2", "region": "CN", "updated_at": "2026-09-08T00:00:00+00:00"},
        {"id": "e-3", "region": "SG", "updated_at": "2026-09-01T00:00:00+00:00"},
    ]
    candidate_rows = [{"id": "e-2"}, {"id": "e-4"}]
    rights = RightsBundle(("forecasting",), commercial_use=True, redistribution=False, jurisdictions=("CN", "SG"))
    product = DataProduct("demand-signals", "Demand signals", DataReference("memory://signals", "json", record_count=len(rows)), "supplier", rights=rights, metadata={"regions": ("CN", "SG"), "freshness_days": 3, "record_count": len(rows)})
    candidate = DataProduct("candidate", "Candidate signals", DataReference("memory://candidate", "json"), "supplier-2", rights=RightsBundle(("forecasting",), commercial_use=True, jurisdictions=("CN",)))
    context = RunContext("stage8-example", config={"records": rows, "left_records": rows, "right_records": candidate_rows, "observed_at": datetime(2026, 9, 11, tzinfo=timezone.utc)})

    governance = {
        "restrictiveness": asdict(RightsRestrictivenessScorer().score(rights, context.started_at)),
        "compatibility": asdict(RightsCompatibilityEvaluator().evaluate(rights, candidate.rights, required=RightsBundle(("forecasting",), commercial_use=True, jurisdictions=("CN",)))),
    }
    profile = {
        "coverage": CoverageProfileMetric().measure(product, "id,region", context),
        "rarity": RarityProfileMetric().measure(product, "region", context),
        "freshness": FreshnessProfileMetric().measure(product, "updated_at", context),
        "joinability": JoinabilityMetric().measure(product, "id", context),
        "overlap": CrossProductOverlapAnalyzer().analyze(product, candidate, context, ("id",)),
    }
    request = EvaluationRequest(task=TaskContext("forecast", "forecasting"), options={"requirements": {"regions": ("CN",), "freshness_days": {"max": 7}, "record_count": {"min": 5}}, "hard_requirements": ("regions",), "weights": {"record_count": 2.0}})
    report = DemandFitEvaluator().evaluate(product, request, (), context)
    output = {"governance": governance, "profile": profile, "demand_fit": asdict(report), "confidence": EvaluationConfidenceEstimator().estimate(report, sample_size=len(rows), population_size=10)}
    target = Path("outputs/stage8-market-readiness/result.json")
    write_json(target, output)
    print(target)


if __name__ == "__main__":
    main()
