# DataEval 业务约束、标签一致性与质量门禁

相关指标基于现有 `QualityMetric.compute` 和 `MetricResult`，不改变 DataEval 模块结构。DataProf 的描述性统计不会直接作为质量分数。

## 指标

- `NumericRangeComplianceMetric`：按最小/最大值和 inclusive 规则检查数值业务范围，缺失、非有限或越界值都生成 evidence；方向为 `HIGHER_IS_BETTER`。
- `LabelConflictMetric`：以实体 ID 聚合标签，检测同一实体出现多个标签的冲突，适合训练集重复标注和主数据合并后的验收。
- `GroupCompletenessParityMetric`：计算不同群组在 required_fields 上的完整率差距，方向为 `LOWER_IS_BETTER`，用于发现区域、客户类型或设备组之间的覆盖不均。
- `TextReadabilityMetric`：使用词数、句数和近似音节数计算 Flesch-style 可读性，并将结果归一化到 0–1；不依赖 NLP 库，低可读性记录保留 evidence。

## 阈值门禁

`EvaluationThresholdGate.evaluate(report, thresholds)` 是一个不修改 `EvaluationReport` 的轻量门禁。它按照 metric 自带的 `ScoreDirection` 判断 `>=` 或 `<=`，输出每项的值、阈值、方向、通过状态和失败数。这样可以把“质量测量”和“项目验收规则”分开：同一个报告可用于不同采购批次、供应商 SLA 或训练集版本，而不需要复制指标实现。

## 与 DataProf/DataGov 的边界

DataProf 负责分位数、熵、相关性和漂移等数据画像；DataEval 负责明确规则下的质量表现和门禁；DataGov 负责权利、血缘和授权；DataValue/DataPrice 只消费评估证据，不在本模块直接生成金额。新指标可以和既有模态指标一起交给 `CompositeEvaluator`，失败指标仍按原有 partial/failed 语义记录。

运行示例：

```bash
PYTHONPATH=src python examples/14_dataeval_quality_gate.py
```

结果位于 `outputs/dataeval-extension/result.json`，包括所有 `MetricResult` 的 statistics/evidence 和最终 gate 状态。
