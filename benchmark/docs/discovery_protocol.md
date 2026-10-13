# 数据挖掘与内容发现协议

## 1. 目标与边界

DataMechBench 不把 benchmark 的价值限制在“谁排第一”。Discovery layer 从已有的
common-case 统计、约束审计、结构轴画像、assumption transfer 和论文预期中提取可复核的
模式，目的是回答：

这里必须区分两层：`discovery_findings.csv` 是高召回率的 **screening layer**，每张卡片
只代表一个待解释的信号；它不能被逐条改写成“24 个研究结论”。主结果必须进一步合并
多个相关信号，形成少量 deep dive，并回答机制原因、替代解释、适用边界和如何证伪。

- 哪些机制差异在相同 cases 上稳定存在；
- 性能排名在加入机制约束后是否改变；
- 平均性能是否掩盖结构敏感性或最差 case；
- 原论文 claim 在哪些实现或 setting 上出现可定位的边界；
- 哪些结果适合形成下一轮独立实验假设。

这些规则是在查看 DataMechBench v0.3 结果后设计并版本化的，因此当前报告属于探索性
分析，不是预注册研究。即使一条 paired finding 通过 Holm 校正和 bootstrap 区间，它也
只是在冻结 case bank 内获得统计支持，仍需 held-out cases 或外部实现复现。

## 2. 发现记录契约

每条 `DiscoveryFinding` 必须记录：稳定 ID、发现类别、证据等级、track/setting、涉及的
mechanism family、指标及方向、主/次效应值、case 和 observation 分母、覆盖率、一句话
结论、解释、限制和下一步验证。发现不能只有自然语言，也不能只链接到排行榜。

证据等级固定为：

| 等级 | 含义 | 不能推出什么 |
|---|---|---|
| `paired_supported` | common-case bootstrap 区间不跨 0，且 setting 内 Wilcoxon 经 Holm 校正后 `p<0.05` | 外部市场普适最优、实际重要性 |
| `constraint_audit` | 应用正式 guardrail 后观察到赢家或资格变化 | DSIC/BIC 等一般理论保证 |
| `design_descriptive` | 冻结结构轴或 assumption-transfer 上的确定性描述 | 结构变量的因果效应 |
| `claim_diagnostic` | 原论文预期在满足已登记 assumptions 的运行中系统性 `not_met` | 对原定理的反证 |
| `hypothesis_generating` | 从多维结果中选择出的性能—稳健性权衡 | 未经独立 cases 验证的确认性结论 |

## 3. 当前七个发现视角

### 3.1 Holm 校正后的成对优势

只接受至少 10 个 common cases、Holm-adjusted `p<0.05` 且 paired-bootstrap 95% 区间
不跨 0 的比较。仅比较论文、官方 adapter、论文变体和成熟项目机制；每个 setting 保留
绝对 oriented mean delta 最大的一条，避免报告被大量近重复 pair 淹没。

### 3.2 约束筛选导致的赢家变化

只检查正式 `SETTING_PRIMARY_METRICS` setting 和完整覆盖机制。当所有 raw rank-1 方法均
为 `fail` 或 `not_auditable`，但存在 constraint-qualified rank-1 时，记录原赢家、合格
赢家、原始名次差和性能差。`not_auditable` 始终不等于 pass。

### 3.3 结构轴最强正/负响应

在三个旗舰结构轴中，只使用至少 10 cases、block coverage=100% 的论文/项目机制。
定向斜率绝对值至少为 0.04 才报告；每条轴各保留最强正响应和最强负响应。斜率全部转为
越高越好方向，负值表示随结构轴增加而退化。

### 3.4 性能水平—结构响应权衡

若机制 A 的 oriented 平均性能至少比 B 高 0.1，但 oriented slope 至少比 B 低 0.1，
则构成候选 trade-off。每个 setting 按“level gap × slope gap”只保留最明显的一对，并
标为 `hypothesis_generating`。

### 3.5 平均—最差 case 缺口

把 primary metric 统一为越高越好后，计算平均值与最差 case 的距离。每条结构轴保留
缺口最大且 gap≥0.1 的机制。这一视角用于发现平均榜掩盖的局部失效区域。

### 3.6 Assumption-transfer 增益与损失

只使用 source/target coverage 都为 100%、两端约束均 pass/not-required 的已声明 transfer。
每个 transfer 保留 oriented delta 至少为 ±0.02 的最大收益和最大损失。由于 source 和
target case bank 未必只差一个潜变量，结果保持 `design_descriptive`。

### 3.7 论文 claim 边界

只处理 `theorem` 和 `paper_experiment` 预期，选择 family 的 canonical implementation，
忽略 assumptions unmet/N/A。至少覆盖 5 个独立 cases，且 eligible observations 中
`not_met` 比例达到 10% 才报告。分母同时保留 case 数与 seed/observation 数，避免把随机
运行数冒充独立样本。

## 4. 输出与使用方式

- `discovery_findings.csv`：机器可读的发现、效应、分母、限制与 next test；
- `discovery_report.md`：按发现类型组织的论文式解读；
- `structural_curve_points.csv`：用于检查结构发现是否来自异常单点；
- `pairwise_comparisons.csv`、`expectation_results.csv`：用于追溯统计和 claim 证据。

文章中可以把 `paired_supported` 作为“在当前 benchmark 内获得支持”的结果，把
`design_descriptive` 作为机制行为画像，把 `claim_diagnostic` 和
`hypothesis_generating` 作为后续研究问题。不能把 24 条发现当作 24 个独立、预注册的
假设检验，也不能只报告有利于某一方法的发现。

## 5. 下一版本如何提高发现可信度

1. 在 v0.4 case bank 生成前冻结本协议和阈值；
2. 将 v0.3 发现转成少量明确 hypotheses，在 held-out blocks 上验证；
3. 对 claim boundary 使用 official/exact implementation 做 outcome parity；
4. 为 worst-case gap 增加 leave-one-block-out 稳定性分析；
5. 对 assumption transfer 建立只改变一个生成参数的 matched case pairs；
6. 公开所有未入选候选及筛选原因，避免只展示有传播性的结论。

## 6. Deep-dive 升级协议

一个候选只有同时满足以下要求，才可从 screening card 升级为正文发现：

1. 围绕一个明确机制问题组织，而不是围绕某个 CSV 行或某个榜单名次；
2. 至少连接两种证据，例如 case-level 曲线与机制交易容量、constraint status 与性能差、
   attack rank 与 reward magnitude、或 run-level flag 与论文 claim 的聚合语义；
3. 明确区分观测事实、机制解释和推断，不能把 `not_auditable` 写成 observed violation；
4. 至少列出一个能解释同一结果的竞争解释或 protocol mismatch；
5. 给出能区分主要解释与竞争解释的可执行、可证伪实验；
6. 所有正文数字均由独立 CSV 自动生成，完整横向方法保留在 CSV，正文只展示最能回答
   研究问题的机制。

v0.3 依此形成四个专题：采购机制的 auditability gap、厚市场中的三类收敛机制、复制攻击
的 rank/share/score/characteristic 分解，以及随机论文 claim 的聚合尺度。对应产物为
`deep_dive_auditability.csv`、`deep_dive_market_thickness.csv`、
`deep_dive_replication.csv`、`deep_dive_claim_aggregation.csv` 和
`deep_dive_report.md`。
