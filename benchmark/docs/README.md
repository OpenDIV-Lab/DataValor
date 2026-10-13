# DataMechBench 文档导航

文档按“主线、支撑证据、协议、扩展研究”阅读。只有第一组定义 benchmark 的主要 novelty 和开源项目叙事；其余文档提供证据、实现边界或扩展方法调研，不应平铺为同等贡献。论文稿件、venue checklist、作者信息、投稿管理以及复用本 benchmark 的独立论文研究均不存放在本代码库。

## 1. 主线文档

建议按以下顺序阅读：

1. [`core_contribution.md`](core_contribution.md)：唯一的 novelty、technical pillars、贡献和 claim boundary；
2. [`../README.md`](../README.md)：范围、规模、快速运行和扩展入口；
3. [`kdd_heldout_findings.md`](kdd_heldout_findings.md)：冻结 held-out 结果解释。

## 2. 核心证据与现实性边界

- [`aggregate_type_envelope_study.md`](aggregate_type_envelope_study.md)：聚合类型兼容剖面、排序翻转、minimax regret 和 joint admissibility；
- [`heldout_source_cards.md`](heldout_source_cards.md)：held-out 数据来源、转换和禁止解释；
- [`direct_market_transaction_source_audit_2026-10-04.md`](direct_market_transaction_source_audit_2026-10-04.md)：真实市场来源准入漏斗及负向结果；
- [`benchmark_best_practices_research.md`](benchmark_best_practices_research.md)：相邻 benchmark 和设计原则调研；
- [`benchmark_metrology_protocol.md`](benchmark_metrology_protocol.md)：17 个 headline 机制的 method-complete mutation matrix 与来源块榜单稳定性；
- [`source_hierarchy_protocol.md`](source_hierarchy_protocol.md)：时间块、数据集、来源与机构四级证据审计，防止把重复观测误写成跨来源泛化；
- [`discriminability_protocol.md`](discriminability_protocol.md)：固定容差下的并列率、饱和率、方差和约束激活度，解释榜单能否真正区分机制；
- [`pairwise_transfer_protocol.md`](pairwise_transfer_protocol.md)：完整 40 个 headline 方法对从 v1 到 v2 的排序保持、并列、衰减、涌现与反转；
- [`diagnostic_challenge_protocol.md`](diagnostic_challenge_protocol.md)：预先冻结的理论边界小面板，用于区分“setting 分辨率不足”和“机制行为相同”；
- [`oracle_and_resolution_validity.md`](oracle_and_resolution_validity.md)：市场主指标的逐案例 exact oracle 证书，以及完整 headline pair 的固定阈值分辨率包络；
- [`induced_value_gold_protocol.md`](induced_value_gold_protocol.md)：受控诱导类型、直接机制语义与现实主张边界；
- [`governance_and_ethics.md`](governance_and_ethics.md)：许可、隐私、风险和部署边界。

## 3. 协议与可扩展性

- [`case_bank_protocol.md`](case_bank_protocol.md)：development/held-out case bank；
- [`structural_response_protocol.md`](structural_response_protocol.md)：复制、集中度和厚度结构轴；
- [`discovery_protocol.md`](discovery_protocol.md)：screening 与 deep dive 的证据等级；
- [`resource_and_incidence_protocol.md`](resource_and_incidence_protocol.md)：估值查询前沿、市场机制原生资源向量与提供者组别影响；
- [`prospective_and_validity_protocol.md`](prospective_and_validity_protocol.md)：v1-only 选型、v2 前瞻评估和独立有效性分层；
- [`setting_method_expansion_research.md`](setting_method_expansion_research.md)：方法和 setting 扩展调研；
- [`procurement_external_implementation_search.md`](procurement_external_implementation_search.md)：采购机制外部实现搜索边界。

## 4. 实现保真度记录

`reference_fidelity_*.md` 和 `sota_adapter_provenance.md` 是逐机制审计记录。它们回答“本地对象与哪篇论文/仓库一致、有哪些偏差”，不各自构成独立 benchmark contribution。

## 文档维护规则

- 新的主要 benchmark 能力必须先更新 `core_contribution.md`；论文只消费版本化后的项目结论，不反向把稿件产物写回代码库；
- 新实验若不改变三个冻结 RQ，应进入支撑证据或扩展研究，不增加“第五/第六贡献”；
- 运行数字只从生成 artifact 或 manifest 引用，不在多个文档手工维护；
- `not_met`、边界、反例和 N/A 不删除，也不改写为实现失败；
- 内部实施计划和临时搜索记录不进入默认阅读路径。
