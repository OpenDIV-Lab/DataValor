# 市场导向估值第二阶段扩展

本阶段沿用 `ValuationRequest`、`ValuationReport` 和 `ValueEstimate`，将第一阶段产生的需求匹配、覆盖、稀缺、重叠、时效和权利证据转换为任务相关价值。所有方法只产生估值，不产生 bid、quote 或 payment。

`MarketContextValuator` 将需求匹配、质量、时效、权利和供给稳定性作为独立乘数，将稀缺性作为受任务匹配约束的有限溢价，再扣除显式成本和风险金额。每个分项都保存在 `components` 中，避免依赖不可解释的综合输入。

`ScarcityAdjustedValuator` 只在稀缺覆盖与任务相关时增加价值；`IncrementalCoverageValuator` 只计算买方尚未拥有的实体、时间、地域等新增覆盖；`SubstitutionAdjustedValuator` 根据可获得替代品的覆盖、质量和任务相关性折扣，同时保留候选数据的独有部分。

`TimeDecayValuator` 使用任务半衰期和时间敏感度计算历史数据价值；`UpdateStreamValuator` 按更新批次的边际价值、交付概率、质量和折现率汇总有限更新流的现值。二者都明确要求时间参数，不根据当前时间隐式推断。

`ValuationEnsemble` 对多个现有 `ValuationReport` 生成稳健中位数或加权共识、区间和方法分歧；`ValuationSensitivityAnalyzer` 使用不可变 request 副本回放因素扰动；`BudgetConstrainedPortfolioSelector` 在资格、预算和必需分组约束下执行小规模精确选择，大规模时使用确定性价值成本比基线。

运行入口：

```bash
PYTHONPATH=src python examples/21_stage9_market_valuation.py
```

结果写入 `outputs/stage9-market-valuation/result.json`。后续 DataPrice 可以消费这些估值 artifact，但不应直接把任何单个估值分项当作成交价格。
