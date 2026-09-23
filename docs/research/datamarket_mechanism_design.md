# DataMarket 订单匹配与交易控制

DataPrice 负责报价、分配和应付金额，DataMarket 负责订单匹配、规则校验、用量控制和共同收益分配。相关逻辑实现为可独立调用的函数和组件，可用于机制实验、上线检查和争议复核。

## 订单簿匹配

`match_orders` 位于 `src/datavalor/data_market/mechanism_design.py`。它按 bid 金额降序、ask reserve 升序排列，检查产品交集、币种、ACTIVE 挂牌和 `min_quality` 约束，并允许一个 ask 被多个买方分片消耗。输出 `MarketMatch`，包含数量、买卖双方、订单 ID 和买卖差额。该步骤不产生 payment，因而不会和 DataPrice 的 McAfee、VCG 或统一价格清算重复；线上可以把输出交给任何清算机制。

## 机制性质审计

`audit_market_mechanism` 对一组提交订单和 `PricingOutcome` 做可复现审计：

- 买方个体理性：支付不超过其对应 bid 的报告价值；
- 卖方个体理性：收到金额不低于 reserve；
- 弱预算平衡/不亏损：买方支付覆盖卖方收到金额；
- 配置效率：用同一订单簿的可行匹配计算基准剩余，再给出实现福利比和阈值门禁。

结果中的 `properties` 只记录本次运行检查到的性质，单次实验不能证明参与者如实报价或市场达到均衡。`metrics` 保存支付、剩余、基准福利和匹配数，供批量 benchmark 汇总。

## 配额准入与数据交付

`QuotaAdmissionController` 在清算后、实际交付前执行买方—产品配额。超过配额的数量被裁剪，关联 payment 按相同比例缩放，并在 `QuotaDecision.denied` 和 `remaining_quota` 中留下证据。它适合订阅套餐的月度调用上限、政府数据的项目配额或隐私预算映射；不会重新计算单位价格，也不会绕过权利授权。

## 联盟协同与收入分配

`ShapleyRevenueAllocator` 实现 `RevenueAllocator`。联盟价值通过 `RunContext.metadata["coalition_values"]` 传入，键为用 `|` 连接的排序后 actor ID；缺失项按非负贡献之和计算。参与者不超过 `max_exact_players` 时计算精确 Shapley 值，超过时使用固定种子做排列采样。负边际贡献截断为 0，再按总收入归一；金额按币种精度取整，残差计入第一个参与者。diagnostics 记录计算方式、参与者数、联盟值数量和对账结果。

## 示例与验证

运行：

```bash
PYTHONPATH=src python examples/18_data_market_mechanism_design.py
```

示例依次执行匹配、DataPrice 一价清算、机制审计、配额准入和 Shapley 分成，输出到 `outputs/datamarket-mechanism-design/result.json`。对应测试位于 `tests/test_data_market_extensions.py`，覆盖质量门槛、订单优先级、性质判定、配额支付缩放和联盟协同分配。
