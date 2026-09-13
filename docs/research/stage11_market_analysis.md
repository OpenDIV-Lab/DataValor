# 市场匹配与结构分析第四阶段扩展

本阶段继续使用 `Listing`、`MarketSnapshot`、`Bid`、`Ask`、`Money` 和 `PricingOutcome`，补充 DataMarket 清算前后的研究方法，不修改公共市场或价格模型。DataPrice 仍负责最终 allocation 和 payment。

`MultiAttributeMarketMatcher` 先检查 ACTIVE 挂牌、币种、价格以及买方声明的质量、时效、信誉和权利硬门槛，再按价格剩余、质量、时效、信誉和权利适配的显式权重排序。一个 bid 在一次匹配中最多形成一个推荐，ask 数量按推荐结果扣减。

`DemandClusterAnalyzer` 按任务、预算层、地域和币种生成确定性需求群组；`SupplySegmentAnalyzer` 按质量、时效和价格阈值划分有效供给；`MarketGapAnalyzer` 分产品识别无供给、供给不足、买卖价格断层和平衡状态。所有分群都是规则型描述结果，不宣称统计聚类或因果关系。

`BundleDemandMatcher` 使用现有 `Bid.constraints["bundle_mode"]` 表达 AND 或 XOR。AND 要求全部产品可供给，XOR 只保留剩余最大的替代项；随后在总预算和 ask 不重复使用约束下，小规模精确枚举最大化报告剩余，大规模使用确定性贪心基线。它输出匹配建议，不产生真实支付。

`analyze_market_health` 补充买卖双方 HHI、同币种 bid-ask spread、未匹配需求、成交产品数、价格离散度和分组成交率。不同币种存在时不计算无意义的跨币种价差。`detect_market_anomalies` 输出重复挂牌、低质量高报价和同步出价等复核信号，不能直接解释为欺诈判定。

运行入口：

```bash
PYTHONPATH=src python examples/23_stage11_market_analysis.py
```

结果写入 `outputs/stage11-market-analysis/result.json`，可以继续交给既有 DataPrice 机制、市场仿真和 Toolkit benchmark 使用。
