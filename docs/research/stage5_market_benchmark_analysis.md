# 阶段 5：市场仿真、Benchmark 与统计分析

阶段 5 的定位是把阶段 4 的报价/机制变成可重复实验：同一个市场案例在不同参与者策略、机制和随机种子下运行多轮，先保留每次原始观测，再做置信区间、成对比较和 Pareto 前沿分析。这里的“实验结果”不自动升格为均衡、因果效果或激励相容证明。

## 市场仿真

`FiniteMarketSimulator` 每轮完成 `observe → decide → price → observe` 转移，给每个策略绑定独立 `ActorProfile`，记录 actor IDs、bid/ask 数量、下一轮市场状态和机制输出。支持 `strategy_actors` 显式映射，避免将买方画像错误传给卖方策略；结果摘要包括成交轮数、转化率、总/平均收入、报告福利和买方支出。模拟器用 `RunContext.seed` 和 round_id 保证回放确定性，并在 diagnostics 中明确 `equilibrium_claimed: false`。

已实现策略不再是空类：

- `TruthfulStrategy`：私有价值直接出价；
- `FixedShadingStrategy`：固定比例 shading；
- `AdaptiveShadingStrategy`：赢后降低、输后提高 shading，并设置上下界；
- `EpsilonGreedyShadingStrategy`：在离散 shading arms 上按 epsilon-greedy 学习剩余效用；
- `MultiplicativeWeightsStrategy`：按 Hedge 权重随机选择 shading arm；
- `BestResponseGridStrategy`：使用 UCB 在有限网格上搜索经验最佳响应；
- `BudgetPacingStrategy`：按剩余轮数均摊预算，且 bid 不超过剩余预算；
- `ContextualShadingStrategy`：根据竞争者数量、轮次进度和预算比率计算线性 shading；
- `FixedReserveSellerStrategy`：每轮发布固定数量和 reserve 的 ask。

这些算法用于机制敏感性、策略学习和预算消耗实验；它们没有访问未授权的对手私有信息，也不声称在任意机制下无悔或收敛。

## Benchmark 矩阵

`MatrixBenchmarkRunner` 执行 component × case × repetition 矩阵。每个单元的 seed 由 `SHA-256(base_seed, component, case_id, repetition)` 生成，因而扩展组件或调整顺序不会改变其他单元。每个 `BenchmarkObservation` 保留 component、case、repetition、measurements、seed 和错误 witness，默认先收集 raw observations，再由 `aggregate_observations` 计算均值、标准差、最小/最大值和失败计数。

`MarketOutcomeMetric` 输出 welfare、seller revenue、payment total、allocation/payment 数量、trade 和可选 efficiency；`SimulationReportMetric` 输出有限轮 conversion rate、总收入、平均收入、收入波动和平均福利。指标将 reported welfare 与 seller revenue 分开，避免将收入误作社会福利。

## 统计与多目标分析

统计工具包括：

- bootstrap mean interval：返回均值、置信区间、标准误、样本量、重采样数和 seed；
- paired difference：返回逐案例差值、均值差、标准差和标准误；
- paired bootstrap difference：保留同一 case/repetition 的配对关系；
- regret summary：计算有限轮累计遗憾、平均遗憾和最大遗憾；
- Pareto frontier：支持每个目标分别指定 max/min 方向；
- scalarized score：按业务权重给多目标候选排序。

`BootstrapAnalyzer`、`PairedComparator` 和 `ParetoFrontierAnalyzer` 会返回 warnings/diagnostics，包括 seed、统计方法、方向和无观测指标。小样本区间仍然只是描述性不确定性，不替代随机化实验设计或稳健假设检验。

## 可运行示例

运行：

```bash
PYTHONPATH=src python examples/10_stage5_market_benchmark_analysis.py
```

该示例在相同 seller reserve 和 12 轮市场中比较 truthful、fixed shading 和 budget pacing，执行 5 次重复实验，输出 15 条 raw observations；随后对收入/转化率做 bootstrap、对策略做 paired comparison，并以收入最大化、波动最小化构建 Pareto 前沿。结果写入 `outputs/stage5-market/result.json`，对应配置为 `configs/workflows/stage5_market_benchmark.json`。

## 与生产系统的边界

当前阶段不包含实时消息队列、分布式 agent 状态、真实支付、订单履约、网络延迟、对手隐私泄露检测和统计显著性自动决策。生产接入时需要固定数据版本和随机种子、记录环境/依赖版本、对策略观测做权限裁剪、保存不可变实验日志，并在跨机制比较时预先注册目标方向、预算和失败处理规则。

