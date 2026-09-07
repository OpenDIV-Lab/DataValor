# 阶段 1 实现说明：数据产品、治理、画像与质量评估

阶段 1 已经在不改变统一主链路的前提下，补齐了可运行的 `DataGov`、`DataProf` 和 `DataEval` 基线。它们只产生治理决定、描述性事实和质量证据，不生成估值金额、报价或支付。

## 1. 运行入口

```bash
PYTHONPATH=src python examples/05_stage1_governance_profile_eval.py
```

示例输入为 [stage1_quality_records.jsonl](../../data/examples/stage1_quality_records.jsonl)，包含一条重复记录、一条缺失 email 和一个错误类型的 `score`。脚本将结果写入 `outputs/stage1-quality-summary.json`，并打印摘要：元数据字段数和 canonical SHA-256、目录命中、用途策略、敏感字段数量、画像修复前后的差异数，以及每个质量指标的状态和统计量。

若需要检查统一主链路的 artifact 和 lineage，可运行：

```bash
PYTHONPATH=src python examples/06_stage1_unified_workflow.py
```

该脚本加载 `configs/workflows/stage1_quality.json`，通过 `UnifiedWorkflowRunner` 执行三个阶段：`governance` 产出 metadata/policy/security bundle，`profile` 产出 `DatasetProfile`，`evaluation` 产出 `EvaluationReport`。结果位于 `outputs/stage1-workflow/`；评估 artifact 同时引用两个输入 artifact 和前置阶段，因而可以沿父引用复盘“哪份数据、哪次运行、用的哪套规则”。

## 2. DataGov 的具体实现

### `LocalMetadataExtractor`

`LocalMetadataExtractor.inspect(product, context)` 会读取 `DataProduct.data.uri`（也可以从 `RunContext.config["records"]` 注入离线记录），然后：

1. 使用 canonical JSON 行序列计算 SHA-256；
2. 统计记录数和字段集合；
3. 推断 `boolean`、`number`、`string`、`mixed` 和 `unknown` 类型；
4. 根据字段名识别 email、phone、name、location 和 identifier；
5. 记录缺失数、distinct 数量、格式、tags、rights 和运行 ID；
6. 返回标准 `MetadataRecord` 和 `FieldSchema`。

字段名识别是保守的启发式规则，不代表法律意义上的个人信息识别。生产环境应通过 DataHub/OpenMetadata、PII 分类器或人工审核 adapter 替换或补充。

### `InMemoryMetadataCatalog`

提供可测试的 `upsert/get/search` 实现：以 `product_id` 作为键，支持 owner、tag、文本、字段分类和 limit 筛选，结果按 `product_id` 排序以保证离线测试确定性。生产环境可以将同一接口替换为 DataHub 或 OpenMetadata connector。

### `RightsPolicyEvaluator`

策略按以下规则检查：

- `valid_until` 是否已过期；
- operation 是否在 `RightsBundle.purposes` 中；
- commercial/sale 是否被 `commercial_use=False` 禁止；
- redistribution/resale 是否被 `redistribution=False` 禁止。

高严重度（HIGH/CRITICAL）finding 会导致 `DENY`；没有高严重度 finding 且未声明用途时为 `REVIEW`；其余情况为 `ALLOW`。这使“需要补充授权材料”和“明确禁止使用”可以区分，具体的 review 规则仍可由项目方在更高层策略中补充。

### `SensitiveFieldScanner`

扫描器复用本地 metadata extractor，对 email、phone、name 和 location 字段生成带字段名和 evidence 的 `GovernanceFinding`。它输出 `SecurityReport`，与 `GovernanceReport` 分开，避免把“发现风险”和“是否允许执行”混成一个分数。

四个本地实现会在导入 `datavalor.data_gov` 时以 lazy factory 形式注册到 `METADATA_EXTRACTORS`、`METADATA_CATALOGS`、`POLICY_EVALUATORS` 和 `SECURITY_SCANNERS`；也可以直接实例化类进行依赖注入。

## 3. DataProf 的具体实现

### `BasicDataProfiler`

对每个字段输出 inferred type、count、missing count、distinct count、数值字段的 min/max/mean/sum、类别字段最多 20 个值的频率分布和 `Evidence("profile.field")`。`ProfileRequest.sample_size` 截取确定性的前 N 行；`fields` 限制字段集合；`options["records"]` 支持测试或上游 artifact 注入。画像只记录“数据是什么样”，不判断统计量是否合格。

### `BasicProfileMetric`

提供单字段或数据集级轻量度量，适合被 registry 或自定义 profiler 调用。返回值是描述性 mapping，不会伪装成 `MetricResult` 或质量分数。

### `BasicProfileComparator`

比较两个 `DatasetProfile` 的 record count、字段新增/删除、字段 missing count 和字段 distinct count，输出带 reference/current 值与 delta 的 `ProfileDifference`。它不对差异做“好/坏”判断；漂移阈值由 DataEval 或 DataGov policy 决定。

`BasicDataProfiler`、`BasicProfileMetric` 和 `BasicProfileComparator` 同样注册到 `PROFILERS`、`PROFILE_METRICS` 和 `PROFILE_COMPARATORS`，因此既可按类调用，也可通过 registry 名称创建。

## 4. DataEval 的具体实现

### `CompletenessMetric`

对选定字段的所有单元计算：

```text
completeness = (cell_count - missing_cells) / cell_count
```

空数据集返回 0，并在 statistics 中保留 0 行、0 字段和 0 单元，避免把“没有数据”误判为完美质量。

### `DuplicateRateMetric`

先对每行 key/value 做排序和字符串规范化，再计算：

```text
duplicate_rate = (record_count - unique_count) / record_count
```

该指标的方向是 `LOWER_IS_BETTER`，不是“越高越好”的质量总分。

### `FieldValidityMetric`

支持 `required_fields`（字段必须存在且非空）和 `field_types`（string/number/boolean/integer）两类约束。每个约束检查都计入分母，避免只统计失败项造成虚高分数；输出 invalid 数量和前 100 条样本级 evidence，超出部分通过 `evidence_truncated` 标记，避免报告无限膨胀。重复记录使用 canonical JSON hash，字段顺序变化不会被误判为不同记录。

### `CompositeEvaluator`

按传入顺序执行多个 `QualityMetric`，保留各自完整的 `MetricResult`。单个 metric 失败不会覆盖成功结果：全部成功为 `succeeded`，部分成功为 `partial`，全部失败为 `failed`；失败信息进入 `diagnostics.failures`，包括 metric 名、异常类型和消息。它不会把不同单位的指标简单平均成所谓“综合价值”。

三项质量指标和 composite evaluator 会注册到 `QUALITY_METRICS`/`EVALUATORS`，可直接执行 `QUALITY_METRICS.create("basic.completeness")` 等调用。

## 5. 阶段 1 与后续阶段的边界

阶段 1 可以独立用于数据产品登记、质量门禁、供应方 SLA、数据版本比较、训练数据清洗前筛查和采购前验收。

阶段 1 输出给 DataValue 的应该是 `MetadataRecord`、`DatasetProfile` 和 `EvaluationReport` 的 artifact 引用。DataValue 再根据 buyer/task/utility 估值；DataPrice 再根据估值、市场规则和 bid/ask 计算报价与支付。阶段 1 本身不会因为 completeness=0.95 就直接生成 95 元或 950 元价格。

阶段 2 的估值入口为 `examples/07_stage2_task_valuation.py`，配置为 `configs/workflows/stage2_valuation.json`。它把阶段 1 的治理、画像和质量评估作为上游证据，再显式传入买方、任务和 adoption cost，生成 `ValuationReport`；同时对每个样本运行 Monte Carlo Shapley，生成带 `std_error`、样本数和随机种子的 `ContributionReport`。阶段 2 的输出仍不包含 bid、quote、allocation 或 payment，价格计算继续由 DataPrice 负责。

## 6. 已知边界

- 当前本地 profiler 面向普通 Python records，不负责大规模分布式计算；Spark/Deequ 应通过已有 adapter 接入。
- 字段分类基于名称启发式，不能替代法务或隐私专业判断。
- 类型推断对混合列返回 `mixed`，不会擅自把字符串数字转换成数值。
- 缺失值只按 `None` 判断；空字符串、特殊缺失码和 NaN 需要在项目规则中显式标准化。
- 画像 comparator 目前不计算分布距离；漂移可在后续接入 Evidently 或自定义 DataEval metric。
- `CompositeEvaluator` 记录失败但不自动重试；重试和超时属于外部 runner 或 adapter 的职责。

## 7. 本轮 DataGov 增量

阶段 1 的治理边界现在还包括四个可直接调用的实现：`LineageGraph`、`RightsMatrixEvaluator`、`MetadataDiff` 和 `GovernanceAuditBundle`。它们只扩展已有模型，不改变统一 workflow：血缘图使用节点/边保存转换、配置 hash 和 checksum，并以 BFS 找出受影响的 evaluation、valuation、quote；权利矩阵把用途、商业使用、再分发、司法辖区、到期时间与 actor/task 约束合并为可解释决策；版本 diff 对字段删除、类型变化、checksum、记录数和权利收紧做 breaking/re-evaluation 分类；审计 bundle 保留报告、证据引用、血缘摘要和下游重算建议。完整规则和运行示例见 [DataGov 血缘、权利与版本扩展](datagov_lineage_rights_versioning.md)。
