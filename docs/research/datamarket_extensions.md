# DataMarket 增量：挂牌、信誉、激励与交易执行

本轮新增实现位于 `src/datavalor/data_market/extensions.py`，继续使用现有 `MarketCatalog`、`IncentivePolicy`、`TransactionProcessor`、`Listing`、`MarketSnapshot` 和 `TransactionRecord`。DataMarket 处理市场参与和交易流程，DataPrice 仍负责 quote、allocation、payment 的计算。

## 挂牌排序

`rank_listings` 对 ACTIVE 挂牌按文本匹配、标签匹配、质量、新鲜度和买方偏好进行确定性排序。它不重新计算价格，也不绕过 `MarketCatalog.discover` 的权利过滤；适合在已授权结果中进一步排序推荐。

## 信誉评分

`score_reputation` 从 `TransactionRecord` 统计 completed、failed、disputed 和 success rate，并按 `success_rate - 0.5 × dispute_rate` 得到 0–1 的 reliability score。交易数量和争议 ID 保留在 evidence 中，可用于供应商排序、保证金策略或人工复核，不把信誉分直接当作价格。

## 贡献激励预算

`ContributionIncentivePolicy` 将固定预算按正贡献比例分配给市场参与者；全部贡献为零时使用等额分配，金额按分币种量化。激励作为 `Incentive` 单独返回，不改变 DataPrice 的成交支付，也不模拟参与者策略。

## 幂等交易处理

`IdempotentTransactionProcessor` 根据 mechanism、allocation 和 payment 内容生成稳定交易 ID；同一 `PricingOutcome` 重复提交会返回已有记录。注入的 `delivery_check` 可以标记产品交付失败，并将状态区分为 succeeded、partial、failed。该组件只记录交易执行状态，不连接真实支付网关。

## 市场统计

`market_statistics` 输出 active listing 数、seller 数、seller HHI、参与者数量、角色构成和最近机制名称，可用于市场快照和 benchmark。它是描述性统计，不代替 DataPrice 的福利计算或 DataMarket 的多轮仿真报告。

运行示例：

```bash
PYTHONPATH=src python examples/17_data_market_lifecycle_incentive.py
```

示例结果写入 `outputs/datamarket-extension/result.json`，展示挂牌排序、信誉、激励预算和市场统计。

