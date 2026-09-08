# DataPrice 增量：分段、订阅、风险和弹性定价

本轮新增实现位于 `src/datavalor/data_price/extensions.py`，沿用 `PricingModel`、`OnlinePricingModel`、`PriceQuote` 和 `PricingOutcome`。DataPrice 只负责价格计算、价格约束和结果核对；挂牌、参与者行为、市场发现和多轮仿真仍由 `src/datavalor/data_market/` 负责。

## 分段用量定价

`TieredUsagePricingModel` 接收 `(upper_bound, unit_price)` 阶梯，并按 progressive 方式收费。比如前 100 条按 1 元、接下来 100 条按 0.5 元，150 条的价格为 `100×1 + 50×0.5 = 125`，不是把全部记录按最低一档计价。每档数量和金额都写入 `PriceQuote.components`，便于核对账单。

## 订阅与超额

`SubscriptionPricingModel` 将周期费、包含用量、超额单价和承诺折扣拆开计算。总价为折扣后的周期费加超额费用，quote diagnostics 保留 billing period；适合按月/季度授权和 API 调用配额。它不负责续费、扣款或客户生命周期。

## 风险调整报价

`RiskAdjustedPricingModel` 从 `estimated_value`、`std_error`、`buyer_share` 和 `rights_factor` 计算买方可接受价格，再扣除 `risk_aversion × 1.96 × std_error`，最后投影到 floor/ceiling。风险惩罚、权利系数、估值和价格上下界都保留在 components 中，因此可以解释“估值 1000 元但报价低于 500 元”的原因。

## 需求弹性调价

`ElasticityPricingModel` 是一个有状态的 `OnlinePricingModel`。每次 `observe` 根据实际购买量与目标量的比值更新价格：

```text
new_price = old_price × (1 + learning_rate × elasticity × (realized/target - 1))
```

价格始终不低于 0，并记录 observation 次数。它只消费已发生的数量反馈，不模拟买方策略；参与者策略和市场均衡实验应使用 DataMarket 的仿真模块。

## 报价校准与结果审计

`calibrate_quotes` 比较 quote 与实际成交价，返回 MAE、RMSE、signed error 和 acceptance rate，并检查币种一致性。`audit_pricing_outcome` 检查 payment/卖方收入对账、负支付和负数量，输出 `valid`/`invalid` 状态。这些工具用于账单回放、模型校准和机制测试，不替代真实支付网关或结算系统。

运行示例：

```bash
PYTHONPATH=src python examples/16_data_price_models_audit.py
```

结果写入 `outputs/dataprice-extension/result.json`。示例同时展示分段、订阅、风险和弹性报价，并对两笔报价做成交价校准。

