# DataValor architecture

## 1. Scope

DataValor 把一条数据产品流程拆成几个可以独立替换的模块。研究者可以只使用估值或定价部分，也可以把治理、评估、交易和受控查询串起来。模块之间通过带版本的 artifact 连接；可选依赖只在真正执行对应能力时加载。

这份文档描述的是当前代码的边界，不是对某个行业系统的部署承诺。表格中的 candidate output 是接口约定，具体算法、存储和服务连接由应用项目提供。

| Stage | Module | Primary question | Candidate output |
|---|---|---|---|
| Value Discovery | DataGov | Is the data governed, authorized, traceable and safe to process? | governance manifest, policy decisions, lineage |
| Value Discovery | DataProf | What is in the data? | schema and statistical profile |
| Value Discovery | DataEval | How good is the data under stated dimensions and tasks? | quality/evaluation vector and evidence |
| Value Discovery | DataValue | What contribution or utility does it have for a user/task/model? | value estimates with uncertainty and explanation |
| Value Circulation | DataMarket | How do suppliers, buyers and platforms interact? | allocation/outcome/strategy traces |
| Value Circulation | DataPrice | What payment or price follows from value, rights and market rules? | prices, payments, revenue and mechanism diagnostics |
| Value Realization | DataQuery | How can authorized users consume and act on the data? | governed query/agent traces and answers |

## 2. Critical semantic boundaries

The following quantities remain separate so their meaning stays clear:

```text
profile facts
  -> evaluation metrics
  -> buyer/task-specific utility or contribution
  -> bids and market context
  -> allocation and transaction payment
  -> realized downstream outcome
```

- A profile records descriptive facts.
- Quality is multi-dimensional and may be task-conditioned.
- Valuation models utility or contribution for a stated user and task.
- Price/payment is a mechanism outcome that can differ from value.
- Realized value is established with downstream evidence and can differ from an ex-ante estimate.

## 3. Planned extension contract

Before adding concrete algorithms, each module should agree on four small concepts:

1. `Component`: named, versioned implementation with declared capabilities;
2. `RunContext`: seed, configuration, rights/policy decision and environment metadata;
3. `Artifact`: versioned payload plus lineage, checksums and diagnostics;
4. `Registry`: explicit component discovery with lazy loading for heavy optional dependencies.

### 3.1 Stage-0 unified workflow

阶段 0 的具体实现位于 `datavalor.core.workflow`。`WorkflowSpec` 从 JSON/YAML 读取一个有序 stage 列表；每个 `WorkflowStage` 声明 handler、输入来源、artifact kind、schema version 和参数。`UnifiedWorkflowRunner` 只负责解析输入、调用 handler、创建 `ArtifactEnvelope`、写入 `ArtifactStore` 和收集失败诊断，领域算法仍由各业务模块或应用方提供。

执行规则是确定的：stage 只能引用初始输入或前序 stage；成功 artifact 的 ID 为 `{workflow_id}/{run_id}/{stage_id}`，`parents` 保存直接输入的 artifact 引用；handler 返回嵌套 envelope 会被拒绝。必需 stage 抛出异常时停止后续执行，并写入 `workflow.failure` artifact（包含错误类型、消息、阶段、traceback 和已有父引用）；可选 stage（`required: false`）失败后会标为 `partial` 流程并继续。

本地 JSON store 使用原子写入和 SHA-256 校验：写入返回带文件 URI/checksum 的 `ArtifactRef`，读取时如果调用方提供 checksum 且不匹配会立即失败。完整链路配置和合成输入分别位于 `configs/workflows/stage0_unified.json` 与 `data/examples/stage0_records.jsonl`，可运行入口为 `examples/00_unified_value_chain.py`。链路中的 `UsageEvent` 记录查询次数、返回行数、计算时间和隐私预算等计量信息，供后续按量计费和实际收益校准使用；它不改变 `PriceQuote` 或 `Payment`。

### 3.2 Stage-1 本地基线

阶段 1 的本地实现位于各模块的 `builtins.py`，不需要第三方依赖：`LocalMetadataExtractor` 生成字段 schema、敏感字段分类、记录数和 canonical checksum；`InMemoryMetadataCatalog` 提供可检索的元数据目录；`RightsPolicyEvaluator` 检查用途、商业使用、再分发和有效期；`SensitiveFieldScanner` 输出字段级治理证据；`BasicDataProfiler`/`BasicProfileComparator` 生成并比较描述性画像；`CompletenessMetric`、`DuplicateRateMetric`、`FieldValidityMetric` 与 `CompositeEvaluator` 生成带 evidence 的质量报告。它们只输出 metadata/profile/evaluation，不把质量指标转换成价格。完整说明见 [阶段 1 实现说明](research/stage1_data_product_governance.md)。

阶段 1 同样提供统一 runner 配置 `configs/workflows/stage1_quality.json` 和入口 `examples/06_stage1_unified_workflow.py`。治理阶段把 metadata、policy、security 作为一个 bundle 保留，画像阶段输出描述性事实，评估阶段接收前两阶段结果并输出质量指标；三阶段 artifact 都写入本地 store，评估 artifact 的 parents 同时记录初始数据和治理/画像阶段，方便后续估值模块按证据引用而不是重新读取原始数据。

阶段 2 的统一入口为 `examples/07_stage2_task_valuation.py`，配置为 `configs/workflows/stage2_valuation.json`。它在同一条链路中追加任务上下文、买方偏好和成本，调用 `WeightedUserTaskValuator` 生成价值估计，并用 `TabularTaskUtility` 驱动 Monte Carlo Shapley 生成样本贡献。估值和贡献 artifact 记录 utility 假设、随机种子、标准误和父引用，但不生成价格或支付。

阶段 3 的统一入口为 `examples/08_stage3_advanced_valuation.py`，配置为 `configs/workflows/stage3_advanced_valuation.json`。它进一步执行质量调整和情景估值、受限符号估值、线性模型训练/预测、精确与分组 Shapley、两两交互和 Bootstrap 稳定性，再按贡献分摊价值；结果保留公式、系数、RMSE、区间、规模边界和父引用，仍与 DataPrice 的报价和支付分离。

### 3.4 阶段 4：DataPrice 报价与机制基线

阶段 4 沿用前述 artifact 链路，不重新设计 workflow：阶段 3 的 `estimated_value`、质量向量、权利和成本进入 `QuoteRequest`，由 `PricingModel` 产生 `PriceQuote`，随后由 `PriceConstraint` 做价格带/量价折扣投影，最后由 `PricingMechanism` 根据 bid、ask、supply 和预算计算 `PricingOutcome`。新增的 cost-plus、value-based、usage-based、quality/freshness 和在线需求调整模型都可独立替换；统一使用 Decimal-backed `Money` 并记录 quote 有效期、组成项和诊断。

多单位统一价格拍卖支持数量出价、部分成交和边际成交价；预算采购支持跳过不可负担 ask、最后一个 ask 部分购买，质量感知采购按质量/成本比排序。性质检查组件输出个体理性、预算可行和容量可行的 witness，便于回放测试。该阶段只计算应付金额和收入，不承诺支付清算、税费、交付或激励相容；具体公式、复杂度、测试边界和生产替换点见 [阶段 4 调研与实现说明](research/stage4_pricing_mechanisms.md)。可运行入口为 `examples/09_stage4_pricing_and_mechanisms.py`，配置为 `configs/workflows/stage4_pricing.json`。

External third-party libraries should normally be wrapped behind adapters that translate their native results into DataValor artifacts. The adapter records the external package/version and preserves native details rather than flattening all outputs prematurely. DVMK is a deliberate exception because it is an existing in-scope codebase: selected DVMK source will be ported, attributed, and substantially refactored into native `datavalor.*` modules, with no runtime dependency on `dvmk`.

## 4. Data and output policy

- `data/examples`: tiny synthetic or clearly redistributable inputs;
- `data/dataflow_data`: small schema fixtures connecting modules;
- `outputs`: generated local results, ignored by default;
- benchmark downloads and user datasets: external cache locations, kept out of automatic commits;
- all commercial data-market examples: explicit rights, consent, retention and resale checks.

## 5. Near-term implementation sequence

1. Freeze common artifact schemas and terminology. The stage-0 implementation now includes `WorkflowSpec`, `UnifiedWorkflowRunner`, a JSON workflow configuration, and an offline end-to-end example under `examples/00_unified_value_chain.py`.
2. Freeze a DVMK source snapshot, then selectively port and refactor evaluation, valuation, pricing, market simulation, and shared research utilities into native DataValor modules.
3. Add OpenDataVal/pyDVL benchmark adapters while keeping them optional dependencies.
4. Select one governance/profile stack and one query stack through thin integrations.
5. Build the Web UI once CLI/API artifacts are stable.
