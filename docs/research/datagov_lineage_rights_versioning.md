# DataGov 血缘、权利矩阵与版本影响

这些实现沿用 `MetadataExtractor`、`PolicyEvaluator` 和统一 workflow 的输入输出，并使用现有的 `MetadataRecord`、`DataProduct`、`GovernanceReport` 与 `ArtifactRef`。它们用于判断字段变更的下游影响、买方操作是否符合授权，以及新版本是否需要重新评估和报价。

## 血缘和影响分析

`LineageGraph` 是有向图，节点用 `LineageNode` 表示，类型可以是 `source`、`dataset`、`data_product`、`evaluation`、`valuation`、`quote` 或任意应用自定义类型；边用 `LineageEdge(source_id, target_id, relation, metadata)` 表示。`metadata` 保存 transformation 名称、配置 hash、字段映射和运行 ID，不会把原始数据载入图中。

上下游查询使用 BFS，复杂度为 `O(V+E)`；拓扑排序使用 Kahn 算法，同样为 `O(V+E)`。`add_edge` 会拒绝缺失节点和自环，`topological_order` 会在外部目录导入环路时抛出错误。`lineage_digest()` 对排序后的节点、边及元数据做 canonical SHA-256，可作为缓存键和审计证据。`validate()` 额外提示没有 transformation 说明的派生边，但不会阻止研究型数据进入图。

`build_lineage_graph` 可以从 `MetadataRecord.lineage` 自动创建 source → product 边，再接收 evaluation/valuation/quote 等 `ArtifactRef` 节点和应用自定义边。`trace_upstream`、`trace_downstream` 和 `affected_artifacts` 返回稳定排序的节点，适合生成变更工单。source 变更时应筛选 evaluation、valuation、quote 和交付产物，并逐项检查旧 checksum；图算法只给出影响范围，不替代各模块重算。

## 权利矩阵

`RightsMatrixEvaluator` 在 `RightsPolicyEvaluator` 的基础检查之外，引入 actor、task、请求权利和确定的 `evaluated_at`。操作名建议统一使用 `query`、`model_training`、`derive`、`sale`、`redistribution`、`quote` 等值。任一 HIGH/CRITICAL finding 为 `DENY`；没有硬拒绝但存在未声明权利/辖区为 `REVIEW`；全部约束满足才是 `ALLOW`。

检查包括：任务用途是否在 `RightsBundle.purposes`；商业操作是否明确 `commercial_use=True`；再分发是否明确 `redistribution=True`；请求辖区是否为授权辖区子集；`valid_until` 是否按 UTC 过期；以及 actor 的 `forbid_redistribution`、task 的 `required_purpose` 等买方约束。`None` 不会被简化为允许。`rights_intersection` 对多个授权取用途/辖区交集、最早到期时间，商业和再分发只有全部明确为 True 才为 True。

## 版本差异和重算门禁

`compare_metadata_records` 比较字段新增/删除、类型、nullable、语义分类、约束、source/owner/license、record_count、sha256、rights 和其他 properties。字段删除、类型/语义/约束变化会进入 `breaking_changes`；checksum 变化即使 schema 不变，也意味着数据内容变化。`compare_products` 在没有 catalog 记录时从 `DataProduct.data` 和 rights 构造最小 metadata，仍可发现 schema_ref、数量、checksum 和授权变化。

`MetadataDiff` 的三层门禁分别表示：schema 或统计变化时重跑 DataEval；质量/统计、来源或权利变化时重跑 DataValue；这些变化以及权利/来源变化时重新生成 DataPrice 报价。`requires_re_evaluation(diff, "quality"|"value"|"price"|"quote")` 可直接作为 workflow 条件节点。标签等普通 metadata 改动通常不触发质量重算，但 owner/license 变化仍建议治理审核。

## 审计 bundle 与边界

`build_governance_audit` 把 metadata、治理报告、安全报告、血缘 digest、版本 diff 和相关 `ArtifactRef` 聚合为 `GovernanceAuditBundle`。它不复制数据 payload，也不创建新的 artifact store；`as_payload()` 可交给现有 artifact store 的上层 envelope。`summary()` 给出严重度计数和 `rerun_data_eval`/`rerun_data_value`/`rerun_data_price` 建议，`digest()` 用于不可变审计索引。

DataGov 负责来源、权利和变化门禁；DataEval 负责重新计算质量指标；DataValue 负责面向任务重新估值；DataPrice 负责重新报价。示例 `examples/12_datagov_lineage_rights_audit.py` 展示 source → evaluation → valuation → quote 的完整影响链和 v1/v2 权利收紧场景。
