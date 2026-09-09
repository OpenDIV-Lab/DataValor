# DataMarket 机制设计与市场专有能力

DataPrice 回答“这份数据应如何报价、如何分配和收款”；DataMarket 还要回答“哪些订单可以相遇、交易是否满足市场规则、交易后如何控制使用量并分配共同收益”。本轮新增代码把这些问题落到可执行的纯函数和组件，方便做机制实验、上线前门禁和争议复核。

## 订单簿匹配

`match_orders` 位于 `src/datavalor/data_market/mechanism_design.py`。它按 bid 金额降序、ask reserve 升序排列，检查产品交集、币种、ACTIVE 挂牌和 `min_quality` 约束，并允许一个 ask 被多个买方分片消耗。输出 `MarketMatch`，包含数量、买卖双方、订单 ID 和买卖差额。该步骤不产生 payment，因而不会和 DataPrice 的 McAfee、VCG 或统一价格清算重复；线上可以把输出交给任何清算机制。

## 机制性质审计

`audit_market_mechanism` 对一组提交订单和 `PricingOutcome` 做可复现审计：

- 买方个体理性：支付不超过其对应 bid 的报告价值；
- 卖方个体理性：收到金额不低于 reserve；
- 弱预算平衡/不亏损：买方支付覆盖卖方收到金额；
- 配置效率：用同一订单簿的可行匹配计算基准剩余，再给出实现福利比和阈值门禁。

结果中的 `properties` 只陈述这一次运行能观测到的性质，不把单次实验当作策略真实或均衡证明；`metrics` 保留支付、剩余、基准福利和匹配数，便于批量 benchmark。

## 配额准入与数据交付

`QuotaAdmissionController` 在清算后、实际交付前执行买方—产品配额。超过配额的数量被裁剪，关联 payment 按相同比例缩放，并在 `QuotaDecision.denied` 和 `remaining_quota` 中留下证据。它适合订阅套餐的月度调用上限、政府数据的项目配额或隐私预算映射；不会重新计算单位价格，也不会绕过权利授权。

## 联盟协同与收入分配

`ShapleyRevenueAllocator` 实现 `RevenueAllocator`。通过 `RunContext.metadata["coalition_values"]` 提供联盟价值（键为排序后的 actor ID，用 `|` 连接），缺失项使用非负贡献之和。参与者不超过 `max_exact_players` 时计算精确 Shapley 值，更大联盟用固定种子做排列采样；负边际贡献会被截断并按总收入归一，最后分币种量化并把残差确定性地归到首个参与者。诊断记录是否精确、玩家数、联盟值数量和是否对账，便于解释数据联合建模、跨机构数据空间等场景的收益分配。

## 示例与验证

运行：

```bash
PYTHONPATH=src python examples/18_data_market_mechanism_design.py
```

示例依次执行匹配、DataPrice 一价清算、机制审计、配额准入和 Shapley 分成，输出到 `outputs/datamarket-mechanism-design/result.json`。对应测试位于 `tests/test_data_market_extensions.py`，覆盖质量门槛、订单优先级、性质判定、配额支付缩放和联盟协同分配。
