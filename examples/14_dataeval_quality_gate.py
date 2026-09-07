"""DataEval 增量示例：业务范围、标签冲突、公平性和阈值门禁。"""

from __future__ import annotations

import json
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_eval import (
    EvaluationReport,
    EvaluationRequest,
    EvaluationThresholdGate,
    GroupCompletenessParityMetric,
    LabelConflictMetric,
    NumericRangeComplianceMetric,
    TextReadabilityMetric,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    rows = [
        {"id": "a", "group": "east", "score": 0.82, "label": "keep", "text": "Reliable demand observations for regional forecasting."},
        {"id": "a", "group": "east", "score": 0.95, "label": "drop", "text": "Duplicate identifier with conflicting label."},
        {"id": "b", "group": "west", "score": 1.20, "label": "keep", "text": ""},
    ]
    product = DataProduct("quality-gate", "Quality gate fixture", DataReference("memory://quality-gate", "json"), "owner")
    request = EvaluationRequest(options={"records": rows})
    context = RunContext("stage-eval-gate")
    metrics = (NumericRangeComplianceMetric("score", 0, 1), LabelConflictMetric(), GroupCompletenessParityMetric("group", ("score", "text")), TextReadabilityMetric())
    results = tuple(metric.compute(product, request, context) for metric in metrics)
    report = EvaluationReport(product.product_id, results)
    gate = EvaluationThresholdGate().evaluate(report, {"tabular.numeric_range": 0.95, "tabular.label_conflict": 0.99, "tabular.group_completeness_parity": 0.20, "text.readability": 0.10})
    output = {"metrics": [result.__dict__ for result in results], "gate": gate}
    path = ROOT / "outputs/dataeval-extension/result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(path), "gate_status": gate["status"], "failed": gate["failed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
