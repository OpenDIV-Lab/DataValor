# 市场需求适配

本文说明 DataGov、DataProf 和 DataEval 中供估值与定价使用的市场需求指标，不涉及订单、合同和支付。

DataGov 的 `RightsRestrictivenessScorer` 将用途、商业使用、再分发、辖区、排他性和期限保留为独立限制因素；`RightsCompatibilityEvaluator` 计算多产品共同可用的权利范围；`ArtifactStalenessEvaluator` 根据年龄、数据 checksum 和 breaking change 判断已有评估产物能否复用。分数仅描述限制程度，不直接作为价格。

DataProf 的 `CoverageProfileMetric`、`RarityProfileMetric`、`FreshnessProfileMetric` 和 `JoinabilityMetric` 描述覆盖、长尾、记录年龄与键质量。`CrossProductOverlapAnalyzer` 给出产品间精确重叠和候选产品的边际新增覆盖。这些结果不解释质量或价值。

DataEval 的 `DemandFitEvaluator` 将显式需求分为硬约束和软偏好，分别保留实际值、期望值、权重与通过状态。`EvaluationConfidenceEstimator` 根据样本覆盖、可测指标覆盖和采样质量估计证据置信度。`EvaluationThresholdGate` 保持原数值阈值兼容，同时支持 `min`、`max` 和 `required` 规则。

运行入口：

```bash
PYTHONPATH=src python examples/20_stage8_market_readiness.py
```

结果写入 `outputs/stage8-market-readiness/result.json`。输出可用于市场估值、稀缺性调整和增量覆盖估值，但不会把画像或适配分数直接转换为金额。
