# 结构响应画像协议

## 1. 为什么不能只看平均榜

机制设计关心的不只是一个方法在 case bank 上的平均效用，还关心它对关键市场结构变化的
响应。相同均值可能来自完全不同的机制行为：一个方法可能在所有市场上稳定居中，另一个
方法可能在薄市场失效、只在厚市场接近最优。静态平均榜会把这两种行为压成同一个数。

DataMechBench 因而在正式榜之外生成 **structural mechanism profile**。它回答三个问题：

1. 机制在结构轴上的总体性能水平如何；
2. 随结构压力变化，性能是改善、稳定还是退化；
3. 最差 case 和设计分块覆盖是否足以支持这一解释。

该画像是诊断证据，不生成跨指标复合分数，也不替代约束合格榜和配对统计检验。

## 2. 当前冻结的三条结构轴

| Setting | 结构轴 | 分块变量 | Primary metric | 结构含义 |
|---|---|---|---|---|
| `V-REPLICATION-ROBUSTNESS` | `replication_factor` | dataset × attacked owner (`replication_group_id`) | `replication_owner_rank_change`，越低越好 | 复制次数增加时，被攻击 owner 是否获得更多相对排名收益 |
| `P-MARKET-CONCENTRATION` | `largest_singleton_share` | `budget_item_count` | `oracle_ratio`，越高越好 | 最大单卖方价值占比增加时，预算机制的配置效率如何变化 |
| `T-MARKET-THICKNESS` | `efficient_trade_count` | `surplus_margin_profile` | `gain_from_trade_ratio`，越高越好 | 有效交易数增加时，有限交易损失是否被厚市场摊薄 |

分块变量控制主要 nuisance factor。不同预算、数据集/owner 或 surplus-margin profile 先各自
形成一条曲线，再等权宏平均，避免 case 较密的分块支配结论。

## 3. 计算协议

评估单位为 `mechanism family × primary-eligible case`。计算顺序固定如下。

1. 只保留 `completed` 且具有正式 primary metric 的结果；oracle、diagnostic reference 和
   `primary_metric_eligible=false` 的 control 不进入画像。
2. 同一 family/case 的随机 seeds 先取均值；`observation_count` 保留实际 seed 数。
3. 在每个设计分块内，把结构轴线性归一化到 `[0, 1]`。归一化仅改变尺度，不改变点序。
4. 把 primary metric 定向为“越高越好”：maximize 指标保持原值，minimize 指标取负值。
5. 每个分块分别计算折线 AUC、最小二乘斜率、末端减起点和相邻点不退化比例。
6. 上述量在设计分块间等权宏平均。`mean_primary` 也先在分块内平均、再跨分块平均；
   `worst_case_primary` 保留所有有效 case 中的最差原始值。
7. `coverage_ratio` 的分母来自完整设计 case bank，包括只有 skipped/failed 结果的分块；
   因而失败分块不能从分母中消失。case 的轴或分块元数据发生冲突时直接报错。

设定向后的分块曲线点为 `(x_i, y_i)`，其中 `x_i ∈ [0,1]`。核心量为：

```text
oriented_axis_auc       = trapezoidal integral of y over x
oriented_slope          = OLS slope of y on x
oriented_endpoint_change = y(x=1) - y(x=0)
nondegradation_rate     = fraction of adjacent differences >= 0
```

所有 oriented quantities 均统一为越高越好。因此负斜率或负 endpoint change 表示机制随
结构轴增加而退化。AUC 更偏向总体曲线水平，slope/endpoint 更偏向结构敏感性；二者不能
互相替代。

## 4. 如何解读

- **高均值、高 AUC、近零斜率：** 性能高且对该轴不敏感；仍需检查约束和实现 fidelity。
- **低均值、正斜率：** 在轴起点较弱，但随市场条件改善而收敛，典型如薄市场损失。
- **高均值、负斜率：** 当前平均表现好，但在结构压力增加时退化，应检查端点和最差 case。
- **均值好、worst case 差：** 平均榜掩盖了结构性失败；不能只引用平均名次。
- **coverage < 1：** 画像只覆盖部分设计分块，不应与完整覆盖机制直接作强结论。

当前完整实验展示了静态榜无法直接表达的差异：Volume Shapley 的复制攻击收益水平很高，
但 2× 到 4× 的额外斜率接近零；Robust Volume Shapley 的平均攻击收益显著更低，却仍有
小幅负向定向斜率。采购中 Proportional Share 的平均效率高于 CGL/JT 核心，但其集中度
斜率为负，而后者为正。交易中 SBBA 保持较高水平且随市场变厚改善；Trade Reduction 和
MUDA 的起点更弱、厚市场改善斜率更大。这些是机制适用边界，而不是新的总排名。

## 5. 产物与扩展契约

- `structural_curve_points.csv`：可直接画图的 seed 聚合曲线点；
- `structural_profiles.csv`：每个 family/setting 的分块宏平均画像；
- `structural_profiles.md`：面向读者的紧凑结果表。

新增结构轴必须同时满足：有明确机制问题和论文/理论依据；至少两个有序轴点；存在可解释
的 nuisance block；primary metric 的方向和资格已登记；case metadata 中提供稳定的轴与
分块字段；至少五个相关机制可比较。扩展时在 `STRUCTURAL_AXIS_SPECS` 注册字段，并增加
轴端点、seed 聚合、缺失分块覆盖和冲突元数据测试。

## 6. 有效性边界

结构画像描述的是冻结 case bank 上的响应，不是因果效应或机制定理证明。当前设计点并非
独立自然市场；OLS slope 会压缩非线性响应，AUC 也依赖所选轴范围。论文报告应同时提供
原始曲线点、case bank 定义、约束状态、paper fidelity 和 common-case 配对统计，不能把
画像单独包装为通用市场结论。
