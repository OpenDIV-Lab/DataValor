"""阶段 1：真实执行数据产品治理、画像和质量评估。

运行：PYTHONPATH=src python examples/05_stage1_governance_profile_eval.py
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from datavalor.core import DataProduct, DataReference, RightsBundle, RunContext
from datavalor.data_eval import (
    CompletenessMetric,
    CompositeEvaluator,
    DuplicateRateMetric,
    EvaluationRequest,
    FieldValidityMetric,
)
from datavalor.data_gov import (
    InMemoryMetadataCatalog,
    LocalMetadataExtractor,
    RightsPolicyEvaluator,
    SensitiveFieldScanner,
)
from datavalor.data_gov.data_product import adapter_from_uri
from datavalor.data_prof import BasicDataProfiler, BasicProfileComparator, ProfileRequest

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data/examples/stage1_quality_records.jsonl"


def main() -> None:
    product = DataProduct(
        "stage1-customer-quality-v1",
        "客户分群质量检查样本（合成）",
        DataReference(str(DATA_PATH), "jsonl"),
        "data-owner",
        rights=RightsBundle(purposes=("quality_assessment", "valuation"), commercial_use=False),
        tags=("customer", "quality", "synthetic"),
        metadata={"license_id": "CC-BY-4.0-DEMO"},
    )
    context = RunContext("stage1-demo-001", seed=17)
    rows = adapter_from_uri(DATA_PATH).materialize()

    metadata = LocalMetadataExtractor().inspect(product, context)
    catalog = InMemoryMetadataCatalog()
    catalog.upsert(metadata, context)
    policy = RightsPolicyEvaluator().evaluate(product, "model_training", metadata, context)
    security = SensitiveFieldScanner().scan(product, {"redact": True}, context)

    profiler = BasicDataProfiler()
    profile = profiler.profile(product, ProfileRequest(options={"records": rows}), context)
    repaired = [dict(row, email=row.get("email") or "unknown@example.test", score=float(row["score"]) if str(row["score"]).replace(".", "", 1).isdigit() else None) for row in rows]
    revised = profiler.profile(product, ProfileRequest(options={"records": repaired}), context)
    comparison = BasicProfileComparator().compare(profile, revised, context)

    evaluation = CompositeEvaluator().evaluate(
        product,
        EvaluationRequest(options={"records": rows, "required_fields": ("id", "email", "region", "score"), "field_types": {"score": "number"}}),
        (CompletenessMetric(), DuplicateRateMetric(), FieldValidityMetric()),
        context,
    )
    summary = {
        "product": asdict(product),
        "metadata": asdict(metadata),
        "catalog_hit": catalog.get(product.product_id, context) is not None,
        "policy": asdict(policy),
        "security": asdict(security),
        "profile": asdict(profile),
        "profile_comparison_after_repair": asdict(comparison),
        "evaluation": asdict(evaluation),
        "interpretation": {
            "policy_is_not_quality": True,
            "quality_is_not_price": True,
            "expected_findings": ["email 缺失", "score 类型错误", "重复记录"],
        },
    }
    output = ROOT / "outputs/stage1-quality-summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"output": str(output), "metadata_fields": len(metadata.fields), "policy": policy.decision.value, "security_findings": len(security.findings), "profile_differences": len(comparison.differences), "evaluation": evaluation.summary}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
