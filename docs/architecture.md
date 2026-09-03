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
