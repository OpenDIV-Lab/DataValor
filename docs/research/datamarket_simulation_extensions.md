# DataMarket 仿真扩展

静态拍卖只能回答给定订单下的成交结果；市场仿真还要表达产品新鲜度、参与者进出、隐私或查询预算以及多轮流动性变化。实现保留 `FiniteMarketSimulator` 的 `reset/step/run` 接口，并在其外围增加可组合的状态变换和结果统计。

## 新鲜度衰减

`decay_market_freshness` 每轮从挂牌或产品 metadata 读取 `freshness`，按固定衰减量更新到 `[0, 1]`。低于 `suspend_below` 的 ACTIVE 挂牌会变成 SUSPENDED，状态中保留每个 listing 的新鲜度和暂停原因。该模型可替换为时间指数衰减或 DataProf 的漂移分数，适合实时行情、IoT 和时效性训练集。

## 参与者冲击

`apply_participation_shock` 在轮次边界处理供应商/买方进入和退出：退出供应商的 ACTIVE 挂牌自动暂停，新参与者按 actor ID 去重加入，需求倍率写入快照 state。可以用它做冷启动、供应商故障、监管退出和需求峰值的敏感性实验。

## 隐私预算

`PrivacyBudgetLedger` 独立记录每个买方的预算、已用量和剩余量，`consume` 采用原子检查，超预算请求不会部分扣除。`PrivacyAwareStrategy` 在生成 truthful bid 时扣除每单位隐私成本；成交后按数量消耗预算。隐私预算不等同于支付金额，便于将 ε、查询次数或脱敏成本映射为不同维度的资源约束。

## 市场健康指标

`summarize_simulation` 从 `SimulationReport` 计算：成交轮数和转化率、总收入、平均成交额、价格标准差、卖方收入 HHI、卖方收入 Gini、买方覆盖率和单位交易福利。它补足了原 runner 只输出总收入/福利的不足，可直接用于策略 benchmark、市场公平性分析和回归测试。

运行示例：

```bash
PYTHONPATH=src python examples/19_data_market_simulation_dynamics.py
```

结果写入 `outputs/datamarket-simulation-dynamics/result.json`。测试位于 `tests/test_data_market_simulation_extensions.py`，覆盖新鲜度暂停、参与者冲击、预算原子性和市场指标统计。
