# 外部开源仓库功能复用规划

本文面向 DataValor 的**外部依赖封装**，与 DVMK 的内部实现迁移分开规划。E0 已完成 capability probe、optional extra 声明和适配器错误边界；E1 已落地 DataEval/DataProf 的五类可选适配器；E2 已落地 pyDVL、OpenDataVal 与 WILDS 的估值和基准适配器；E3 已落地 DataHub、OpenMetadata 与 Deequ/Spark 的治理 connector；E4 已落地 Mesa、PySyft 与 Ocean.py 的市场和仿真 adapter；E5 已落地 DB-GPT/Vanna 风格的 DataQuery 规划、执行和结果防护链路。外部仓库只在适配器边界被局部调用，不复制整仓库源码。

## 1. 复用边界

外部仓库只提供某一类能力的后端或算子，DataValor 始终保留自己的公共模型、权限边界、产物 schema 和 registry。推荐调用链为：

```text
DataValor request/model
  -> 外部库 adapter（可选依赖）
  -> 外部库局部 API
  -> DataValor result/evidence/artifact
```

外部库通过 adapter 转换为 DataValor 公共 API；整仓库、大型 CLI、Web 应用和内部 runner 保持在核心包之外。

## 2. 按模块的候选仓库与 import 形态

| DataValor 模块 | 外部仓库 | 复用内容 | 推荐封装位置 | 预计 import 形态 |
|---|---|---|---|---|
| DataValue | pyDVL | Shapley、semivalue、least-core、influence 的单次计算器 | `data_value/backends/pydvl.py` | `import pydvl.valuation as pydvl_valuation`（函数内延迟导入） |
| DataValue/Benchmark | OpenDataVal | AME、DVRL、KNN-Shapley、LAVA、Data-OOB 的统一实验适配 | `toolkit/benchmark/backends/opendataval.py` | `from opendataval import DataEvaluator as _ODVLEvaluator`（adapter 内） |
| DataEval | Cleanlab | label issue、outlier、duplicate、Datalab issue summary | `data_eval/backends/cleanlab.py` | `from cleanlab import Datalab`（optional extra） |
| DataEval/DataProf | fg-data-profiling | DataFrame profile、字段统计、报告结构 | `data_prof/backends/fg_profile.py` | `import ydata_profiling as _profile`（以发行包实际名称为准） |
| DataEval | Evidently | drift/test/report snapshot | `data_eval/backends/evidently.py` | `from evidently import Report`（按版本 capability 检查） |
| DataGov/DataEval | Great Expectations | expectation、checkpoint、validation result | `data_gov/backends/great_expectations.py` | `import great_expectations as gx` |
| DataGov/DataEval | Deequ | Spark 规模质量约束和指标计算 | `data_gov/backends/deequ.py` | 通过 JVM 服务或 job artifact 连接 |
| DataEval/Benchmark | TorchMetrics | metric state、update/compute、聚合和测试模式 | `data_eval/backends/torchmetrics.py` | `from torchmetrics import Metric`（仅 torch extra） |
| DataMarket/Simulation | Mesa | agent、scheduler、datacollector | `data_market/simulation/backends/mesa.py` | `from mesa import Agent, Model` |
| DataGov/DataMarket | PySyft | owner-side execution、权限和远程数据操作 | `data_gov/backends/syft.py`、`data_market/backends/syft.py` | `import syft as _syft`（服务/隔离环境优先） |
| DataMarket | Ocean.py | asset/service 注册、发现和消费流程 | `data_market/backends/ocean.py` | `from ocean_lib import Ocean` 或按当前 SDK 文档适配 |
| DataGov | DataHub | metadata、lineage、ownership ingestion | `data_gov/backends/datahub.py` | `from datahub.emitter.rest_emitter import DatahubRestEmitter` |
| DataGov/DataQuery | OpenMetadata | catalog、lineage、governance API | `data_gov/backends/openmetadata.py` | 通过 `from metadata.generated.schema...` 或 REST client 连接平台 |
| DataQuery | DB-GPT | connector、Text-to-SQL、agent service | `data_query/backends/dbgpt.py` | HTTP/SDK client，查询前经过 `QueryAuthorizer` |
| DataQuery | Vanna | RAG-to-SQL 交互参考 | `data_query/backends/vanna.py` | 仅在 successor 明确后再 `import vanna` |
| Toolkit/Benchmark | WILDS | shift dataset、官方 split、评估器 | `toolkit/benchmark/backends/wilds.py` | `from wilds import get_dataset` |
| Toolkit/Benchmark | DataPerf | data-centric benchmark 提交和任务设计 | `toolkit/benchmark/backends/dataperf.py` | 采用 CLI/文件产物 adapter，按需接入平台能力 |

实际实现时，外部 import 放在 adapter 方法或 capability probe 内；公共 `datavalor` 模块在未安装可选依赖时保持可导入。

## 3. 各仓库的具体复用策略

### pyDVL：DataValue 高优先级后端

按算法粒度调用估值或 influence 计算器，将 DataValor 的 `ValuationRequest` 转为 pyDVL 输入，再把结果映射成 `ValueEstimate`/`ContributionReport`。公共层保留 DataValor schema，依赖作为可选 extra 管理。

### OpenDataVal：统一 benchmark 后端

复用其数据污染、算法比较和评测矩阵思想。DataValor adapter 负责准备 `BenchmarkCase`、固定随机种子、读取 raw observation，并把外部结果转换为 `BenchmarkObservation`；实验 runner 和结果目录留在适配器内部。

### Cleanlab：质量问题证据算子

按需调用 Datalab 或 label issue finder，保留样本级 issue、issue type、severity 和证据 URI，写入 `MetricResult.evidence`；价格计算继续使用 DataPrice 的定价流程。

### Great Expectations / Evidently / Deequ：验证和监控后端

将 expectation、checkpoint、drift test 或 Spark 约束封装成 `QualityMetric`/`GovernanceFinding`。保留外部报告 URI 和检查明细，再由 DataValor 统一状态、诊断和 lineage。

### fg-data-profiling / TorchMetrics：画像和指标结构

借鉴 profile/metric 的状态和聚合实现，必要时通过 DataFrame adapter 转换数据。TorchMetrics 仅在 torch 可选环境启用，并将 `update`/`compute` 生命周期桥接到 DataValor 的 `compute`。

### Mesa：复杂市场仿真后端

把 DataValor `ParticipantStrategy` 映射成 Mesa Agent，把 `MarketSnapshot` 映射成 Model state；每轮通过 DataValor `SimulationStep` 回传，DataValor 公共模型保持统一。

### PySyft / Ocean.py / DataHub / OpenMetadata：服务或 SDK 边界

这些项目体量大、生态耦合强，优先采用 REST/SDK connector。DataValor 负责授权、超时、重试、审计和 artifact 封装，外部平台数据库、身份系统和区块链协议留在 connector 边界内。

### DB-GPT / Vanna：DataQuery 后端

所有自然语言查询都先经过 `QueryAuthorizer` 和 `ResultGuard`。外部 agent 生成候选 query 或执行计划，DataValor 负责策略检查、脱敏、执行目标和 trace 记录。

### WILDS / DataPerf：Benchmark 数据和任务

优先复用官方数据集加载器、split 定义和任务元数据；输入经过 `BenchmarkDataProvider`，输出转换成 DataValor artifact。数据集本身、模型权重和大体积缓存按外部数据管理策略存放。

## 4. 分阶段利用计划

### 阶段 E0：依赖边界与 capability probe

- 为每个候选仓库建立 adapter 目录和 `requires` capability 名称；
- 增加 optional dependency group，但不改变基础安装；
- 定义缺少依赖、版本不兼容、服务不可达时的明确异常；
- 增加 import audit，确保核心包不加载外部重型依赖。

当前实现：`datavalor.core.capabilities` 提供 `probe_capability`、`probe_capabilities`、`require_capability` 和 `CapabilityStatus`；`datavalor.toolkit.probe_external_capabilities` 提供统一清单探测。对应配置见 `configs/integrations/capabilities.yaml`。

### 阶段 E1：DataEval/DataProf 外部算子

- Cleanlab label issue；
- Great Expectations validation；
- Evidently drift；
- fg-data-profiling profile；
- TorchMetrics 聚合指标；
- 统一 `MetricResult`、`Evidence`、`GovernanceFinding`。

当前实现位于 `src/datavalor/data_eval/backends/` 与
`src/datavalor/data_prof/backends/`：

| 适配器 | 外部 API 选择 | DataValor 输出 |
|---|---|---|
| `CleanlabQualityMetric` | 优先 `Datalab(data=..., labels=...).find_issues()`，旧版回退 `cleanlab.filter.find_label_issues` | issue rate、样本级 `Evidence` |
| `GreatExpectationsMetric` | 注入 validator；否则 `great_expectations.validate` 或 `from_pandas(...).validate()` | expectation pass rate、失败证据 |
| `GreatExpectationsPolicyEvaluator` | 复用上述验证并映射政策决策 | `GovernanceReport/Finding` |
| `EvidentlyDriftMetric` | 注入 runner；否则 `Report(...).run(current_data, reference_data)` | drift-free rate、报告快照证据 |
| `FgDataProfiler` | 注入 builder；否则 `ydata_profiling.ProfileReport` 的 `to_dict/get_description/to_json` | `DatasetProfile/FieldProfile` |
| `TorchMetricsAdapter` | 外部 `Metric.update(...); compute()` 生命周期 | `MetricResult` |

每个适配器的外部模块都通过 `require_capability` 在执行方法内延迟导入；测试使用
callable 注入，不需要联网或预装第三方包。适配器只暴露 DataValor 模型，外部
DataFrame、报告和 metric state 不会泄漏到公共接口。

验收：每个 adapter 都能在依赖缺失时安全导入，在依赖存在时返回 DataValor schema，并保留样本/字段证据。

### 阶段 E2：DataValue 和估值 Benchmark

- pyDVL 贡献度和 influence；
- OpenDataVal 方法适配；
- LAVA 或其他专门方法作为 benchmark case；
- WILDS/DataPerf 数据和 split provider；
- 与 Stage 3 的内部估值实现进行 paired benchmark。

当前实现：

| 适配器 | 外部 API 与兼容边界 | DataValor 输出 |
|---|---|---|
| `PyDVLContributionValuator` | 支持注入 runner/estimator；兼容函数式 valuation 和 estimator `fit`/`values` 结果 | `ContributionReport`、含标准误的 `ValueEstimate` |
| `PyDVLValuator` | 面向 influence 等模型相关分值，runner 显式接收 `ValuationRequest` | `ValuationReport` |
| `OpenDataValValuator` | 支持 callable，也支持 `input_data → train → data_values` 生命周期；按 AME/DVRL/KNN-Shapley/LAVA/Data-OOB 名称解析 | `ValuationReport` |
| `OpenDataValBenchmarkMetric` | 将一次外部方法评估映射为命名 measurements | `BenchmarkMetric.measure` 的纯量字典 |
| `WILDSDataProvider` | 调用 `wilds.get_dataset`，默认禁止下载，使用 `get_subset` 官方 split，并把样本转成可移植 records | `ArtifactEnvelope` |

pyDVL 结果中的 `indices`、`values` 和可选 `stderr` 会分别进入目标 ID、数值和
`ValueEstimate.uncertainty`。WILDS 的 Tensor/array 通过 `tolist()` 转为普通 Python
数据，未物化模式只返回数据集描述符，不把外部 Dataset 对象放入 DataValor payload。
所有 adapter 均支持 callable/estimator/loader 注入，因此测试和离线部署不需要网络。

验收：外部算法结果进入 `ValueEstimate`/`BenchmarkObservation`，`PriceQuote` 与 `Payment` 仍由 DataPrice 流程生成。

### 阶段 E3：DataGov 目录、血缘和规模验证

- DataHub metadata/lineage emitter；
- OpenMetadata catalog connector；
- Deequ Spark job artifact；
- 统一 ingestion 状态、重试、权限和 lineage。

当前实现：

| 适配器 | 复用方式 | DataValor 输出 |
|---|---|---|
| `DataHubMetadataCatalog` | 注入 `DatahubRestEmitter`/client；真实环境延迟加载 `datahub.emitter.rest_emitter` 与 `mce_builder` | `MetadataRecord`，保留 connector/run 诊断 |
| `DataHubMetadataExtractor` | 从 `DataProduct` 生成 DataHub 兼容的技术元数据，不改变产品数据 | `MetadataRecord/FieldSchema` |
| `OpenMetadataCatalog` | 注入 SDK/REST client；默认延迟构造 `OpenMetadata`，兼容 `create_or_update/upsert/get_by_name/search` | `MetadataRecord` |
| `OpenMetadataExtractor` | DataValor 产品到 OpenMetadata 通用实体字段的映射 | `MetadataRecord/FieldSchema` |
| `DeequValidationAdapter` | 不在 DataValor 内启动 Spark；消费注入的 PyDeequ/Spark job runner | `ArtifactEnvelope`（版本化约束结果） |
| `DeequPolicyEvaluator` | 将 Deequ constraint status/message 转换为治理 finding 与 allow/review 决策 | `GovernanceReport/GovernanceFinding` |

三类 connector 共用 `data_gov.backends._connector`：有限重试、超时关键字透传、
外部异常统一为 `ConnectorError`、映射对象的 JSON/dict 兼容解析。SDK/client/transport
均可注入，因而测试不需要网络；DataHub URN、OpenMetadata entity、Spark DataFrame
和 Deequ constraint 对象不会进入 DataValor 公共模型。

验收：连接器可以离线 mock；真实服务调用均有超时、审计和失败诊断，不影响核心包导入。

### 阶段 E4：DataMarket/Simulation 外部后端

- Mesa agent-based simulation；
- PySyft owner-side execution；
- Ocean.py asset/service market adapter；
- 与 DataValor `MarketSimulator`、`TransactionProcessor` 和 rights 模型对齐。

当前实现：

| 适配器 | 复用方式 | DataValor 输出 |
|---|---|---|
| `MesaMarketSimulator` | 复用 Mesa `Model.step` 调度；participant 决策、价格机制和快照仍由 DataValor 处理 | `SimulationStep/SimulationReport` |
| `SyftOwnerExecution` | 注入 owner-side executor；真实部署才延迟加载 `syft` | 普通 mapping（供受治理执行链消费） |
| `SyftPolicyEvaluator` | rights/purpose 本地硬检查，可选调用 owner-side checker | `GovernanceReport/GovernanceFinding` |
| `SyftTransactionProcessor` | 注入 PySyft execute/client，封装远程交付状态 | `TransactionRecord` |
| `OceanMarketCatalog` | 注入 Ocean client；真实环境延迟加载 `ocean_lib`，仅映射 asset 注册/发现/下架 | `Listing` |
| `OceanTransactionProcessor` | 注入 consume/client，封装链上消费结果 | `TransactionRecord` |

Mesa 的 Agent/Model/collector、PySyft 的 Domain/Datasite 对象以及 Ocean 的 asset/service
对象均不进入 DataValor 公共模型。市场 connector 使用有限重试与 timeout；区块链写入、
数据消费和 owner-side 执行都必须由调用方显式配置 client/executor，不会在导入或构造阶段
自动联网。

验收：外部仿真结果转换为 `SimulationStep` 和 `PricingOutcome`，用户侧统一使用 DataValor schema。

### 阶段 E5：DataQuery 和生产化集成

- DB-GPT connector；
- Vanna successor 评估后再决定是否接入；
- QueryAuthorizer、QueryPlanner、ResultGuard 全链路策略闸门；
- Web UI 消费统一的 DataValor view model。

当前实现：

| 适配器 | 复用方式 | DataValor 输出 |
|---|---|---|
| `RightsQueryAuthorizer` | 基于 `RightsBundle.purposes` 做本地硬授权，可选注入额外 policy | `QueryAuthorization` |
| `DBGPTQueryPlanner` | 注入 DB-GPT client/generator；兼容 `generate_sql`、`ask`、`generate`，真实 SDK 执行时延迟加载 `dbgpt` | `QueryPlan/QueryPlanStep` |
| `VannaQueryPlanner` | 注入 Vanna client/generator；兼容 `generate_sql` 与 `ask` | `QueryPlan/QueryPlanStep` |
| `ExternalQueryExecutor` | 注入数据库/服务 executor；兼容 `run_sql`、`execute`、`query` | `QueryResult` |
| `QueryResultGuard` | 统一执行最大行数、字段脱敏与 truncation 标记 | `QueryResult` + `QueryTraceEvent` |
| `GovernedDataAgent` | 固定 authorize → plan → execute → guard 顺序，拒绝时不调用外部 agent | `QueryResult` + 全链路 trace |

DB-GPT/Vanna 的自然语言响应、SQL、DataFrame 和 agent state 会在 adapter 内转换为
DataValor 的 `QueryPlan`、`QueryResult` 和 `QueryTraceEvent`。外部 agent 不能绕过
`RightsQueryAuthorizer`；SQL 只能作为待检查的 `QueryPlanStep.statement` 进入执行器；
原始结果必须经过 `QueryResultGuard` 才能返回调用方。

验收：请求先经过授权检查，再调用外部 agent；trace 包含查询、执行目标、脱敏和下游 lineage。

## 5. 适配器模板

```python
from datavalor.core import CapabilityUnavailableError, ComponentSpec
from datavalor.data_eval import QualityMetric


class ExternalQualityAdapter(QualityMetric):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            name="external.quality",
            version="0.1.0",
            module="data_eval",
            kind="quality_metric",
            requires=("external-package>=x.y",),
        )

    def compute(self, product, request, context):
        try:
            import external_package  # optional; only loaded when this adapter runs
        except ImportError as exc:
            raise CapabilityUnavailableError(
                "Install the DataValor optional extra for external-package"
            ) from exc
        external_result = external_package.compute(...)
        return self._to_datavalor_result(external_result, product, request, context)
```

适配器负责输入转换、外部调用、输出映射、证据保留、异常翻译、超时/重试和 capability 说明；外部库的 `DataFrame`、报告对象和 agent state 在适配器内转换为 DataValor 公共模型。

## 6. 依赖和配置建议

- 基础安装保持零重型依赖；每个仓库对应独立 optional extra，例如 `datavalor[pydvl]`、`datavalor[quality]`、`datavalor[mesa]`；
- 配置围绕 `backend`、`capabilities`、`timeout`、`retry`、`endpoint` 和数据映射组织，外部仓库配置在适配器内管理；
- 版本范围通过适配器 capability probe 验证，import 阶段不预设外部 API；
- 所有外部调用写入 `ArtifactEnvelope.diagnostics` 和 provenance；
- 服务型依赖使用最小权限、凭据注入和网络边界；
- 外部数据集和模型权重需独立确认隐私、再分发和体积限制；
- 依赖安装和联网调用在具体集成批次中按配置执行。

## 7. 当前结论

截至 E4，已完成的运行时代码与验证如下：

- `data_eval.backends.cleanlab`：Cleanlab `Datalab`/旧版 `find_label_issues` 双路径；
- `data_eval.backends.great_expectations` 与 `data_gov.backends.great_expectations`：验证指标及治理决策适配；
- `data_eval.backends.evidently`：报告运行、drift 指标递归提取和快照证据；
- `data_prof.backends.fg_profile`：ProfileReport 的字典/描述/JSON 多种输出格式转换；
- `data_eval.backends.torchmetrics`：`update(preds, target)` 与 `compute()` 生命周期桥接；
- `data_value.backends.pydvl`：贡献估值、influence/target 分值、索引及标准误转换；
- `data_value.backends.opendataval`：估值生命周期和 benchmark measurement 适配；
- `toolkit.benchmark.backends.wilds`：官方数据集/split 与可移植 artifact；
- `data_gov.backends.datahub` 与 `openmetadata`：目录、字段和 ownership 映射；
- `data_gov.backends.deequ`：Spark/Deequ 约束 artifact 与治理决策；
- `data_market.simulation.backends.mesa`：Mesa 调度与 DataValor 市场快照桥接；
- `data_gov.backends.syft`、`data_market.backends.syft`：owner-side 权限和交易执行边界；
- `data_market.backends.ocean`：资产目录与消费 connector；
- `data_query.backends`：授权、DB-GPT/Vanna 规划、外部执行、结果防护和 DataAgent 编排；
- E1–E5 的离线 mock/injection 测试覆盖输出 schema，整个仓库测试为 89 项通过。

所有实现均不在模块导入阶段加载第三方库；未安装依赖时仅在选中适配器执行时报告
`CapabilityUnavailableError`。这些适配器不会把外部 DataFrame、报告对象或 metric state
暴露给 DataValor 调用方。

E1–E5 已分别扩充 DataEval/DataProf、DataValue/Benchmark、DataGov、DataMarket 与 DataQuery，同时保持 DataValor 核心模型稳定。DB-GPT/Vanna 的生产化部署仍需由具体环境提供 client、数据库连接、凭据和网络策略；Vanna 的后续版本与 AI Economist 等项目继续列入观察名单。
