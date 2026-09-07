"""DataProf 增量示例：稳健统计、集中度、相关性、分层采样和漂移。"""

from __future__ import annotations

import json
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_prof import (
    CategoricalConcentrationMetric,
    DriftAnalyzer,
    PairwiseCorrelationMetric,
    RobustStatisticsMetric,
    stratified_sample,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    reference = [{"region": "east", "sales": 100 + i * 2, "orders": 10 + i} for i in range(8)] + [{"region": "west", "sales": 60 + i, "orders": 8 + i} for i in range(2)]
    current = [{"region": "east", "sales": 180 + i * 2, "orders": 15 + i} for i in range(8)] + [{"region": "north", "sales": 40 + i, "orders": 5 + i} for i in range(2)]
    product = DataProduct("sales", "sales", DataReference("memory://sales", "json"), "owner")
    context = RunContext("stage-dataprof", config={"records": reference})
    robust = RobustStatisticsMetric().measure(product, "sales", context)
    concentration = CategoricalConcentrationMetric().measure(product, "region", context)
    correlation = PairwiseCorrelationMetric().measure(product, "sales,orders", context)
    sampled = stratified_sample(reference, ("region",), 6, seed=42)
    drift = DriftAnalyzer().analyze(product, product, RunContext("stage-dataprof-drift", config={"reference_records": reference, "current_records": current}))
    output = {"robust_statistics": robust, "categorical_concentration": concentration, "pairwise_correlation": correlation, "stratified_sample": sampled, "drift": {"summary": drift.summary, "fields": [result.__dict__ for result in drift.fields]}}
    path = ROOT / "outputs/dataprof-extension/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "drifted_field_count": drift.summary["drifted_field_count"], "sample_size": len(sampled)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

