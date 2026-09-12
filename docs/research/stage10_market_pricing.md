# 市场定价第三阶段扩展

本阶段沿用 `QuoteRequest`、`PriceQuote`、`Money` 和 `PriceConstraint`，将第二阶段估值及市场参照转换为可解释报价。价格区间继续保存在既有 `components` 中，不修改公共报价格式。

`PriceRangePricingModel` 使用估值、估值标准误、价值分成、证据置信度、成本底价和可比价格形成 floor、target 和 ceiling，最终 `PriceQuote.price` 使用 target。`ComparableSelector` 以显式数值或类别特征选择同币种可比商品，`ComparablePricingModel` 使用相似度加权价格并分别应用质量、时效和权利差异。

`RightsDifferentiatedPricingModel` 对商业使用、再分发、排他、地域和期限采用非负溢价，保证相同基准价下更宽权利不会产生更低报价。`FreshnessTierPricingModel` 使用可配置记录年龄阶梯；`VersionDeltaPricingModel` 根据新增覆盖、质量变化和规模变化计算相对上一版本的价格变化。

`BundleDiscountConstraint` 对同币种报价按原价格比例投影，重叠部分折扣、互补部分保留可配置溢价。`audit_price_quotes` 检查成本底价、估值比例、相对历史价格跳变、报价过期和权利价格单调性。权利比较使用逐维偏序；互有宽窄的授权不会被错误判定为严格包含。

运行入口：

```bash
PYTHONPATH=src python examples/22_stage10_market_pricing.py
```

结果写入 `outputs/stage10-market-pricing/result.json`。这些模型产生报价和审计结果，不执行 allocation、payment 或真实结算。
