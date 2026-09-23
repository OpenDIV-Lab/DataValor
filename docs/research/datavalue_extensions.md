# DataValue 风险、反事实、组合与校准

实现位于 `src/datavalor/data_value/extensions.py`，沿用 `ValuationRequest`、`ValueEstimate` 和 `ValuationReport`，不修改估值接口或 DataPrice 的报价对象。

## 风险调整估值

`RiskAdjustedValuator` 接收 `evaluation_vector` 中的 quality，以及 `options["uncertainty"]` 的 `std_error`/区间。质量不确定性先按 `base_value × rights_multiplier` 换算为货币标准误，再以 `risk_aversion × 1.96 × monetary_std_error` 作为风险折扣，最后扣除 acquisition、preparation、adoption、operation 成本。结果保留 quality 与 monetary 两种标准误、95% 区间、风险惩罚和总成本，避免把质量分数单位直接当作金额。

## 反事实增量价值

`CounterfactualValuator` 比较 `evaluation_vector` 与 `baseline_vector`，按 `metric_weights` 汇总指标增量，再乘以 `value_per_unit` 并扣除显式成本。负增量不会生成负价格，而是将价值下限截断为 0；estimate 的 explanation 保留观察向量、基线向量和权重，适合对照实验、模型升级和数据加入前后收益评估。

## 组合价值与协同

`PortfolioValuator` 接收 `portfolio_items`（target_id/value/uncertainty/group）和可选 `synergies`。组合价值为 standalone value 加协同项，减去各项目标准误平方和开根后的风险惩罚；同时输出 group 数和 diversification factor。它用于多个区域、渠道或模态数据一起采购时的组合评估，但不替代 DataPrice 的组合报价或拍卖支付。

## 价值曲线

`build_value_curve(sizes, utilities, total_value)` 将不同数据规模下的任务 utility 转成单调曲线。重复规模先平均，再用 pool-adjacent-violators 算法修复 utility 下降，按最大 utility 将曲线缩放到给定总价值，并返回每个规模点的 marginal utility、cumulative value 和 marginal value。该结果可用于判断下一批数据的边际收益是否覆盖采购或标注成本。

## 估值校准

`calibrate_values(predicted, observed)` 计算 MAE、RMSE、bias、MAPE 和相关系数，用于比较 ex-ante 估值与成交后/任务完成后的实际收益。输入必须是等长且有限的数值；零实际值会从 MAPE 分母中排除，但不会影响 MAE/RMSE。校准结果适合写入分析 artifact，不能直接当成新的价格模型。

## 与其他模块的边界

DataEval 输出 quality/utility 指标，DataValue 根据指定的 buyer 和 task 生成 value estimate。风险调整、反事实和组合方法只输出估值，不生成 bid、quote 或 payment。DataPrice 根据市场规则和供需计算报价与支付。示例见 `examples/15_data_value_risk_portfolio.py`。
