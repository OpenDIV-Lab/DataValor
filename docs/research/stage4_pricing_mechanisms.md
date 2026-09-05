# 阶段 4：报价与市场机制的可运行设计

阶段 4 的目标是把阶段 3 的“买方/任务价值估计”变成可审计的报价和交易结果，同时保持两个语义边界：估值不是价格，交易机制也不等于支付清算。所有金额在边界处使用 `Money(Decimal, currency)`，避免二进制浮点在分账时产生不可追溯的误差。

## 报价模型

`CostPlusPricingModel` 将 acquisition、preparation、operation 三类成本相加，再按 `margin_rate` 计算加成：`quote = (costs × (1 + margin_rate))`。`ValueBasedPricingModel` 接收阶段 3 的 `estimated_value`，乘以 `buyer_share` 后投影到 floor/ceiling；这使价值分成与最终市场出价保持可区分。`UsageBasedPricingModel` 将固定费、记录数、查询次数和计算秒数分别计量，公式为 `fixed + n_records·p_record + n_queries·p_query + seconds·p_compute`。`QualityFreshnessPricingModel` 使用 `w·quality + (1-w)·freshness` 调整基准价，并应用上下界。

`AdaptiveDemandPricingModel` 是一个可复现的在线基线。每次曝光记录 accepted/rejected，价格按 `p ← p(1 + η(s - target))` 更新，其中 `s∈{0,1}`。它适合做 A/B 或有限轮实验；不是需求曲线估计，也不声称均衡或因果效果。实际部署应把观测写入不可变日志，并处理退款、取消、币种和税费。

## 约束和机制

`PriceBandConstraint` 对一组报价执行货币一致的 floor/ceiling 投影，保留原报价 ID、组成项和投影诊断；`VolumeDiscountConstraint` 按数量阈值使用最高匹配阶梯折扣。它们是显式的约束阶段，而不是悄悄修改估值。

`MultiUnitUniformPriceAuction` 对数量出价按金额降序排序，在 supply 内进行部分分配；供给约束绑定时，所有赢家支付最后一个边际成交报价，供给宽松时支付 seller reserve。输出 allocation、payment、统一单价、总分配量和买方报价减卖方保留价的 welfare。该实现是单产品/同质单位基线，时间复杂度 `O(B log B)`，不处理互补 bundle 或跨币种竞价。

`BudgetAwareProcurement` 按 reserve 升序采购，在最后一个 ask 上允许部分数量，并跳过预算不足的 ask；使用小余量阈值避免 Decimal 除法产生“尘埃数量”。`QualityAwareProcurement` 将顺序替换为 `quality / reserve`，适合预算有限且质量可观测的采购。两者时间复杂度为 `O(A log A)`，不替代供应商履约和结算。

## 可验证性质

`check_individual_rationality` 检查每个买方支付是否不超过其报告 bid 对实际成交数量的价值（数量竞价时 `bid.amount` 按单位报价解释）；`check_budget_feasibility` 检查实际支付是否超出预算；`check_capacity_feasibility` 检查 allocation 是否超过声明 supply。`evaluate_pricing_properties` 汇总检查并返回 violations witness。这里的“holds”只表示给定输入下的算术性质，不是对诚实出价、激励相容、无套利或收入最优的理论证明；这些性质需要额外的机制设计证明或仿真实验。

## 端到端例子和生产边界

`examples/09_stage4_pricing_and_mechanisms.py` 使用同一数据产品和阶段 3 风格的价值估计，生成四种报价，执行价格带与量价折扣，然后运行多单位拍卖、质量感知预算采购和性质检查，结果写入 `outputs/stage4-pricing/result.json`。对应的声明式链路位于 `configs/workflows/stage4_pricing.json`。

生产接入还需要：商品挂牌和版本冻结、买方身份与信用、税费/发票、支付失败和退款、交付回执、反洗钱与制裁筛查、跨币种汇率、bundle 互补/替代、隐私预算和差分隐私成本，以及对价格更新的离线回放和漂移监控。本阶段明确不把这些外部系统伪装成已实现能力。
