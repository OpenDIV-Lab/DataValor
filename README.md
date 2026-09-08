# DataValor

**A Toolkit for Data Valorization**

DataValor 是 DIV Lab 维护的 Python 工具库，主要用来做数据治理、质量评估、估值、定价和流通实验。各模块共享一组简单的数据产品和产物接口，研究代码可以逐步接入，不必先搭一整套服务。

当前版本为 `pre-alpha`。仓库里已经有公共模型、接口、registry、基准实验工具和离线示例；生产环境所需的存储、调度、权限系统和外部服务连接，需要在接入项目中补齐。建议先运行 `examples/` 下的脚本，再替换成自己的数据和后端。

代码按数据流转过程分成三组：

1. **价值发现（Value Discovery）**：DataGov、DataProf、DataEval、DataValue；
2. **价值流通（Value Circulation）**：DataMarket、DataPrice；
3. **价值实现（Value Realization）**：DataQuery。

<a id="module-index"></a>

## 模块索引

下面列出主要模块和对应的源码入口。

<table>
<thead><tr><th>阶段</th><th>模块</th><th>核心职责</th><th>详细说明</th></tr></thead>
<tbody>
<tr><td rowspan="1">公共基础</td><td><code>datavalor.core</code></td><td>组件、数据产品、运行上下文、产物、registry、pipeline、存储协议</td><td><a href="#module-core">Core</a></td></tr>
<tr><td rowspan="4">价值发现</td><td><code>datavalor.data_gov</code></td><td>标准化、清洗、安全、元数据、政策和治理</td><td><a href="#module-datagov">DataGov</a></td></tr>
<tr><td><code>datavalor.data_prof</code></td><td>统计画像、字段属性、分布和画像比较</td><td><a href="#module-dataprof">DataProf</a></td></tr>
<tr><td><code>datavalor.data_eval</code></td><td>多维质量评估、证据和任务效用测量</td><td><a href="#module-dataeval">DataEval</a></td></tr>
<tr><td><code>datavalor.data_value</code></td><td>用户/任务相关估值和数据贡献度</td><td><a href="#module-datavalue">DataValue</a></td></tr>
<tr><td rowspan="2">价值流通</td><td><code>datavalor.data_market</code></td><td>挂牌、发现、参与者、激励、交易、收益分配和仿真</td><td><a href="#module-datamarket">DataMarket</a></td></tr>
<tr><td><code>datavalor.data_price</code></td><td>报价、动态定价、拍卖清算、allocation 和 payment</td><td><a href="#module-dataprice">DataPrice</a></td></tr>
<tr><td>价值实现</td><td><code>datavalor.data_query</code></td><td>授权、查询规划、执行、结果防护和数据智能体</td><td><a href="#module-dataquery">DataQuery</a></td></tr>
<tr><td rowspan="4">公共工具</td><td><code>datavalor.toolkit</code></td><td>对公共 artifact、pipeline、registry 的便捷导出</td><td><a href="#module-toolkit">Toolkit</a></td></tr>
<tr><td><code>datavalor.toolkit.benchmark</code></td><td>数据源、扰动、benchmark metric 和实验矩阵</td><td><a href="#module-benchmark">Benchmark</a></td></tr>
<tr><td><code>datavalor.toolkit.analysis</code></td><td>统计分析、方法比较和 Pareto frontier</td><td><a href="#module-analysis">Analysis</a></td></tr>
<tr><td><code>datavalor.toolkit.webui</code></td><td>与具体 Web 框架无关的 view/app 接口</td><td><a href="#module-webui">Web UI</a></td></tr>
</tbody>
</table>

其他常用位置：

- [仓库结构](#repository-layout)
- [当前功能概览](docs/repo_overview.md)
- [模块间语义边界](#semantic-boundaries)
- [最小扩展方式](#extension-example)
- [安装与验证](#installation)
- [可运行示例](examples/README.md)
- [文档与调研资料](#documentation)
- [制造业黑灯工厂优化设计](docs/intelligent_black_factory_design.md)
- [开发原则](#development-principles)

<a id="repository-layout"></a>

## 仓库结构

```text
DataValor/
├── src/datavalor/
│   ├── core/                     # 公共组件、上下文、产物、registry、pipeline
│   ├── data_gov/                 # DataGov：治理、标准、清洗、安全、元数据
│   ├── data_prof/                # DataProf：统计画像、属性与指标
│   ├── data_eval/                # DataEval：数据质量评估
│   ├── data_value/               # DataValue：数据估值
│   ├── data_market/
│   │   └── simulation/           # DataMarket：参与者策略与市场仿真
│   ├── data_price/               # DataPrice：定价、拍卖和支付
│   ├── data_query/               # DataQuery：智能问数与数据智能体
│   └── toolkit/
│       ├── benchmark/
│       ├── analysis/
│       └── webui/
├── data/
│   ├── examples/
│   └── dataflow_data/
├── tests/
├── outputs/                      # 默认不纳入版本控制
└── docs/
    └── research/                 # GitHub 调研与 DVMK 迁移分析
```

目录名就是 Python import 路径。例如 `DataValue` 对应 `datavalor.data_value`；模块展示顺序和阶段信息可以从 `datavalor.MODULES` 查看。

每个业务模块默认采用相同的内部约定：

```text
module/
├── models.py       # 稳定的 request、result、finding、report
├── interfaces.py   # 抽象接口与行为约定
├── registry.py     # 按能力分类的 typed lazy registry
└── __init__.py     # 经过筛选的公共 API
```

新增实现通常放在 `metrics/`、`valuators/`、`mechanisms/` 或 `providers/` 等子目录，公共模型和接口保持稳定。

<a id="semantic-boundaries"></a>

## 模块间语义边界

各模块通过带版本的 artifact 连接，但每种结果的含义不同：

```text
DataGov 治理与可用性
  -> DataProf 描述性事实
  -> DataEval 质量与任务表现
  -> DataValue 用户/任务相关效用或贡献
  -> DataPrice quote、allocation 与 payment
  -> DataMarket 交易、激励和收入分配
  -> DataQuery 受治理的数据使用与结果
```

使用这些结果时，请区分：

- profile 提供描述性事实；
- evaluation 记录多维质量或任务表现；
- valuation 估计特定用户或任务的效用与贡献；
- bid 表示参与者报告的支付意愿，quote 表示平台报出的价格；
- payment 是机制和市场环境共同产生的交易结果；
- simulation observation 用于记录实验行为，理论性质需要单独分析；
- query answer 在授权、执行和结果防护完成后形成可交付结果。

<a id="module-core"></a>

## Core：公共契约与基础设施

源码入口：[src/datavalor/core](src/datavalor/core)

Core 是所有模块共享的零第三方依赖基础层，集中定义跨模块稳定概念；清洗、估值、拍卖和问数算法由业务模块承载。

### 核心接口和模型

| 名称 | 类型 | 作用 |
|---|---|---|
| `ComponentSpec` | dataclass | 记录组件名、版本、模块、类型、capability 和可选依赖 |
| `Component` | Protocol | 支持结构化扩展的最小组件协议 |
| `BaseComponent` | ABC | 内置实现和类式插件的公共抽象基类 |
| `RunContext` | dataclass | 显式传递 run ID、随机种子、actor、task、rights 和配置 |
| `DataReference` | dataclass | 引用数据 URI、格式、checksum、schema 和记录数 |
| `DataProduct` | dataclass | 可治理、可评估、可估值、可挂牌和可查询的数据产品 |
| `RightsBundle` | dataclass | 用途、商业使用、再分发、排他性、期限和地域限制 |
| `ActorProfile` | dataclass | 供应方、购买方、平台、分析师和 Agent 的最小画像 |
| `TaskContext` | dataclass | 下游任务、目标、utility metric 和约束 |
| `CostContext` | dataclass | 采购、准备、采用和运行成本 |
| `ArtifactEnvelope[T]` | generic dataclass | 统一 schema version、producer、payload、lineage、evidence 和 diagnostics |
| `ArtifactRef` | dataclass | 不加载 payload 的稳定 artifact 引用 |
| `ArtifactStore` | ABC | artifact 的 `put/get/exists` 存储边界 |
| `Registry[T]` | generic class | 延迟工厂、重名保护、组件发现和 registry freeze |
| `PipelineNode` | dataclass | 声明一个组件节点的输入、输出和参数 |
| `PipelineSpec` | dataclass | 声明有版本的组件工作流 |
| `PipelineRunner` | ABC | 执行 pipeline，但不规定存储或调度实现 |

公共导入示例：

```python
from datavalor import ArtifactEnvelope, ComponentSpec, Registry, RunContext
from datavalor.core import DataProduct, DataReference, RightsBundle
```

Core 提供数据引用、上下文、产物和执行协议；数据读取、治理决策、算法运行及输出路径由上层模块按需实现。

[返回模块索引](#module-index)

<a id="module-datagov"></a>

## DataGov：数据治理

源码入口：[src/datavalor/data_gov](src/datavalor/data_gov)

DataGov 管理数据来源、元数据、权利和处理规则，并对具体操作做授权判断。它包含标准化、清洗、安全、元数据和政策接口，也可以接入外部数据目录或合规平台。

### 主要输入与输出

- 输入：`DataProduct`、`StandardDefinition`、治理规则、operation、`RunContext`；
- 输出：`MetadataRecord`、`TransformationPlan`、`TransformationResult`、`SecurityReport`、`GovernanceReport`。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `MetadataExtractor` | `inspect(product, context)` | 提取技术、语义、权利、分类和血缘元数据 |
| `MetadataCatalog` | `upsert/get/search` | 保存并检索治理元数据，可通过适配器连接 DataHub/OpenMetadata |
| `DataStandardizer` | `plan/transform` | 先产生可审计计划，再执行格式、schema 或语义标准化 |
| `DataCleaner` | `plan/clean` | 先产生清洗计划，再物化新的数据引用 |
| `SecurityScanner` | `scan` | 检测敏感字段、泄露、隐私和安全风险 |
| `PolicyEvaluator` | `evaluate` | 针对具体 operation 返回 allow、deny 或 review |

### E3 外部治理 Connector

DataGov 的可选 backend 位于 `datavalor.data_gov.backends`：

- `DataHubMetadataCatalog` / `DataHubMetadataExtractor`：将 DataHub emitter、URN 和字段/ownership 元数据映射为 `MetadataRecord`；
- `OpenMetadataCatalog` / `OpenMetadataExtractor`：将 OpenMetadata SDK/REST client 的 catalog 实体映射为 `MetadataRecord`；
- `DeequValidationAdapter`：消费外部 PyDeequ/Spark job 的约束结果，封装为版本化 `ArtifactEnvelope`；
- `DeequPolicyEvaluator`：将 constraint status/message 转为 `GovernanceFinding` 和 `GovernanceReport`。

DataHub、OpenMetadata 和 Spark/Deequ 都属于可选能力。真实 SDK 只在 adapter 执行时延迟加载；
更推荐在服务部署中注入已配置的 client、emitter 或 Spark runner。connector 统一支持
timeout、有限 retry 和审计诊断，外部 URN、entity、DataFrame 和 constraint 对象不会
暴露给 DataValor 上层。

### 关键模型

`FieldSchema`、`MetadataRecord`、`GovernanceFinding`、`GovernanceReport`、`StandardDefinition`、`TransformationStep`、`TransformationPlan`、`TransformationResult`、`SecurityReport`、`CatalogQuery`。

### 扩展 registry

`METADATA_EXTRACTORS`、`METADATA_CATALOGS`、`STANDARDIZERS`、`CLEANERS`、`SECURITY_SCANNERS`、`POLICY_EVALUATORS`。

DataGov 聚焦来源、权利、处理规则与政策判断；统计画像、质量评估、估值和价格计算分别由 DataProf、DataEval、DataValue 与 DataPrice 承载。

DataGov 目录中还包括四个可单独使用的实现：`LineageGraph` 追踪 source 到 evaluation、valuation、quote 的影响；`RightsMatrixEvaluator` 检查用途、商业使用、再分发、辖区和期限；`MetadataDiff` 比较 schema、checksum、统计量和权利变化；`GovernanceAuditBundle` 汇总治理、安全、血缘和版本证据。规则和示例分别见 `docs/research/datagov_lineage_rights_versioning.md` 与 `examples/12_datagov_lineage_rights_audit.py`。


[返回模块索引](#module-index)

<a id="module-dataprof"></a>

## DataProf：数据画像

源码入口：[src/datavalor/data_prof](src/datavalor/data_prof)

DataProf 生成字段类型、缺失、基数、分布和数据集级属性，并支持不同时间或数据版本之间的画像比较。

### 主要输入与输出

- 输入：`DataProduct`、`ProfileRequest`、字段和采样选项；
- 输出：`FieldProfile`、`DatasetProfile`、`ProfileDifference`、`ProfileComparison`。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `ProfileMetric` | `measure` | 计算一个字段级或数据集级描述性事实 |
| `DataProfiler` | `profile` | 组合统计量形成完整 `DatasetProfile` |
| `ProfileComparator` | `compare` | 比较两个 profile 的描述性变化 |

### 扩展 registry

`PROFILE_METRICS`、`PROFILERS`、`PROFILE_COMPARATORS`。

DataProf 只负责描述数据；分布变化是否可接受，由 DataEval 指标或 DataGov 规则结合具体场景判断。

`advanced.py` 增加了稳健分位数/IQR、类别熵和集中度、Pearson 相关性、固定种子的分层抽样，以及数值 PSI/类别 JS 漂移分析。它们仍返回描述性事实，示例和说明见 `examples/13_dataprof_statistics_drift.py`、`docs/research/dataprof_statistics_drift.md`。

[返回模块索引](#module-index)

<a id="module-dataeval"></a>

## DataEval：数据质量评估

源码入口：[src/datavalor/data_eval](src/datavalor/data_eval)

DataEval 在明确的维度、粒度和任务下计算质量指标，并为每个指标保留方向、单位、统计量、证据和诊断。

### 主要输入与输出

- 输入：`DataProduct`、`EvaluationRequest`、一组 `QualityMetric`、可选 `TaskContext`；
- 输出：`MetricResult`、`EvaluationReport`、`TaskUtilityResult`。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `QualityMetric` | `compute` | 在 sample、group、dataset、product、source 或 window 粒度计算一个指标 |
| `DataEvaluator` | `evaluate` | 调度多个 metric，保留每个结果及其 evidence |
| `TaskUtilityEvaluator` | `evaluate_task` | 通过下游模型或任务实验测量实际 utility |

`MetricResult` 明确包含 `dimension`、`scope`、`value`、`direction`、`unit`、`statistics`、`evidence` 和 `diagnostics`。`ScoreDirection` 支持 `higher_is_better`、`lower_is_better`、`target_is_best` 和 `descriptive`。

### 扩展 registry

`QUALITY_METRICS`、`EVALUATORS`、`TASK_UTILITY_EVALUATORS`。

DataEval 输出质量与任务效用证据，buyer-specific value、bid、quote 和 payment 分别由 DataValue、DataMarket 与 DataPrice 处理。`tabular.py`、`text.py`、`image.py`、`audio.py`、`video.py` 和 `multimodal.py` 分别放置各模态指标；每个指标返回自己的方向、统计量、evidence 和 diagnostics，不把不同模态压成一个分数。统一示例为 `examples/11_stage7_multimodal_evaluation.py`。

`advanced.py` 还包括业务范围合规、重复实体标签冲突、群组完整性差距和无依赖文本可读性指标；`EvaluationThresholdGate` 按各指标方向执行阈值验收。运行入口为 `examples/14_dataeval_quality_gate.py`，规则说明见 `docs/research/dataeval_quality_extensions.md`。

### E1 外部评估适配器

`datavalor.data_eval.backends` 提供可选的外部算子封装：

- `CleanlabQualityMetric`：将 Cleanlab 的 label issue/outlier 结果转为 issue rate 与样本级 `Evidence`；
- `GreatExpectationsMetric`：将 expectation/checkpoint 验证转为 pass rate；`GreatExpectationsPolicyEvaluator` 可进一步生成 `GovernanceReport`；
- `EvidentlyDriftMetric`：将 `Report.run` 的 drift 结果转为 drift-free rate，并保留报告快照；
- `TorchMetricsAdapter`：桥接 TorchMetrics 的 `update`/`compute` 状态生命周期。

这些类在真正执行时才加载第三方包，也可以注入 validator、runner、detector 或 metric。没有安装对应 extra 时，核心包仍能导入，调用适配器会收到明确的 `CapabilityUnavailableError`。

[返回模块索引](#module-index)

<a id="module-datavalue"></a>

## DataValue：数据估值与贡献度

源码入口：[src/datavalor/data_value](src/datavalor/data_value)

DataValue 面向特定用户、任务或模型估计数据及其组成单元的效用和贡献。估值对象可以是 sample、group、dataset 或 data product。

### 主要输入与输出

- 输入：`ValuationRequest`，其中显式包含 product、targets、buyer、task、rights、costs 和 evaluation artifacts；
- 输出：`ValueEstimate`、`ValuationReport`、`ContributionReport`、`TrainingReport`。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `UtilityFunction` | `score` | 计算一个数据子集对任务的 utility |
| `DataValuator` | `value` | 对一个或多个 target 生成价值估计 |
| `TrainableValuator` | `fit/value` | 从历史估值请求和观测结果学习模型 |
| `ContributionValuator` | `value_contributions` | 计算边际贡献或联盟贡献度 |

`ValueEstimate` 包含 `value`、`unit`、可选 `currency`、`components`、`uncertainty`、`explanation` 和 `diagnostics`。`ValuationMode` 区分 model-dependent、model-agnostic、task-specific 和 market-oriented 方法。

### 扩展 registry

`UTILITY_FUNCTIONS`、`VALUATORS`、`TRAINABLE_VALUATORS`、`CONTRIBUTION_VALUATORS`。

DataValue 只负责用户、任务和模型相关的效用与贡献估计，交易报价和清算由 DataPrice 处理。当前实现包括 weighted user-task、requirements、LOO、Shapley、Monte Carlo Shapley，以及 learned/symbolic valuation。

`data_value/extensions.py` 增加了风险调整估值、反事实增量价值、多产品组合协同、单调价值曲线和估值校准：分别对应不确定性折扣、相对 baseline 的收益、portfolio synergy、数据规模的边际价值，以及预测值与实际收益的 MAE/RMSE/bias。示例为 `examples/15_data_value_risk_portfolio.py`，说明见 `docs/research/datavalue_extensions.md`。

### E2 外部估值适配器

`datavalor.data_value.backends` 提供：

- `PyDVLContributionValuator` / `PyDVLValuator`：将 pyDVL 的 Shapley、semivalue 或 influence 结果转换为 `ContributionReport`、`ValuationReport` 和 `ValueEstimate`；
- `OpenDataValValuator`：兼容 OpenDataVal 的 callable 以及 `input_data → train → data_values` 生命周期；
- `OpenDataValBenchmarkMetric`：将外部方法结果接入 Benchmark 的 measurement 接口。

适配器会保留外部结果中的索引和标准误，并映射为 DataValor 的目标 ID 与不确定性字段。没有安装 `valuation` extra 时，模块仍可导入，只有执行适配器才会报告 capability 缺失。

[返回模块索引](#module-index)

<a id="module-dataprice"></a>

## DataPrice：数据定价与机制计算

源码入口：[src/datavalor/data_price](src/datavalor/data_price)

DataPrice 根据估值证据、权利、供需和机制规则生成 quote，并计算 allocation 和 payment。所有货币金额使用 `Decimal` 封装在 `Money` 中。

### 主要输入与输出

- 单产品报价输入：`QuoteRequest`；输出：`PriceQuote`；
- 市场机制输入：`PricingRequest`，包含 products、bids、asks、valuation artifacts、supply、demand 和 market context；
- 市场机制输出：`PricingOutcome`，包含 allocations、payments、welfare、seller revenue、properties 和 diagnostics。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `PricingModel` | `quote` | 生成产品、买方、任务和权利相关的 quote |
| `OnlinePricingModel` | `quote/observe` | 根据完整曝光、接受、数量和收入日志更新状态 |
| `PriceConstraint` | `project` | 执行 no-arbitrage 或其他价格约束 |
| `PricingMechanism` | `price` | 根据 bid、ask、供需和规则计算 allocation/payment |

### 关键模型

`Money`、`QuoteRequest`、`PriceQuote`、`Bid`、`Ask`、`PricingRequest`、`Allocation`、`Payment`、`PricingOutcome`、`PricingObservation`。

### 扩展 registry

`PRICING_MODELS`、`ONLINE_PRICING_MODELS`、`PRICE_CONSTRAINTS`、`PRICING_MECHANISMS`。

DataPrice 负责报价、分配与支付计算；listing 生命周期、参与者管理、数据交付和结算执行由 DataMarket 等上层流程衔接。当前实现包括 VCG、McAfee、posted price、procurement、core-selecting、contextual pricing 和 no-arbitrage 约束。

阶段 4 还提供可直接运行的 `CostPlusPricingModel`、`ValueBasedPricingModel`、`UsageBasedPricingModel`、`QualityFreshnessPricingModel` 和 `AdaptiveDemandPricingModel`，以及价格带、阶梯量价折扣、多单位统一价格拍卖、预算感知/质量感知采购。`evaluate_pricing_properties` 会对个体理性、预算和容量约束给出可审计的 violations witness。报价、估值、支付保持分离：报价模型可参考估值，但拍卖支付由边际出价或 ask reserve 决定。完整公式、复杂度和边界见 [阶段 4 调研与实现说明](docs/research/stage4_pricing_mechanisms.md)，端到端运行 `PYTHONPATH=src python examples/09_stage4_pricing_and_mechanisms.py`。

[返回模块索引](#module-index)

<a id="module-datamarket"></a>

## DataMarket：数据市场与市场仿真

源码入口：[src/datavalor/data_market](src/datavalor/data_market)

DataMarket 负责数据产品挂牌和发现、参与者行为、交易、激励和收入分配。它消费 DataPrice 的 `PricingOutcome`，不另定义价格、allocation 或 payment 对象。

### 主要输入与输出

- 输入：`Listing`、`DiscoveryQuery`、`ActorProfile`、`PricingOutcome`、参与者 contribution 和 `MarketSnapshot`；
- 输出：listing 搜索结果、`Incentive`、`RevenueAllocation`、`TransactionRecord`、`SimulationStep`、`SimulationReport`。

### 市场生命周期接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `MarketCatalog` | `publish/withdraw/discover` | 数据产品挂牌、下架和受治理发现 |
| `ParticipantRepository` | `upsert/get/search` | 保存机制和仿真需要的最小参与者画像 |
| `IncentivePolicy` | `compute` | 在市场价格之外计算参与激励 |
| `RevenueAllocator` | `allocate` | 按贡献或明确规则分配已经实现的收入 |
| `TransactionProcessor` | `execute` | 执行权利、交付和结算并记录部分失败 |

### 市场仿真接口

仿真子模块：[src/datavalor/data_market/simulation](src/datavalor/data_market/simulation)

| 接口 | 方法 | 说明 |
|---|---|---|
| `ParticipantStrategy` | `decide/observe` | 根据获准观察生成 bid、ask 或 abstention，并更新状态 |
| `MarketSimulator` | `reset/step/run` | 以确定性种子运行有限轮市场实验 |

仿真模型包括 `MarketObservation`、`StrategyDecision`、`SimulationStep` 和 `SimulationReport`。仿真结果用于记录实验观察；equilibrium、no-regret 或 incentive compatibility 等理论性质需结合专门分析。

### 扩展 registry

`MARKET_CATALOGS`、`PARTICIPANT_REPOSITORIES`、`INCENTIVE_POLICIES`、`REVENUE_ALLOCATORS`、`TRANSACTION_PROCESSORS`、`PARTICIPANT_STRATEGIES`、`MARKET_SIMULATORS`。

`InMemoryMarketCatalog` 支持按用途、权利、标签和元数据筛选挂牌，`InMemoryParticipantRepository` 支持按角色和属性筛选参与者，`ContributionRevenueAllocator` 负责 Decimal 金额、负贡献截断、分币种残差回补和总额对账。有限轮仿真与策略学习的说明见 [阶段 5 调研与实现说明](docs/research/stage5_market_benchmark_analysis.md)。

DataMarket 负责市场流程、参与者互动、激励、交易和收入分配，并沿用 DataEval、DataValue 与 DataPrice 的结果模型。

### E4 外部市场与仿真适配器

可选 backend 位于 `datavalor.data_market.simulation.backends`、
`datavalor.data_market.backends` 和 `datavalor.data_gov.backends`：

- `MesaMarketSimulator`：使用 Mesa 的 `Model.step` 作为调度层，但每轮仍通过 DataValor 的 `MarketObservation`、`StrategyDecision`、`PricingRequest` 和 `SimulationStep` 完成；
- `SyftOwnerExecution`：把 owner-side 远程执行限制在显式 executor/client 边界；
- `SyftPolicyEvaluator`：先依据 `RightsBundle.purposes` 做本地权限判断，再可选调用 PySyft checker；
- `SyftTransactionProcessor`：将 PySyft 执行状态转换为 `TransactionRecord`；
- `OceanMarketCatalog`：将 Ocean asset 注册、发现和下架流程映射为 `Listing`；
- `OceanTransactionProcessor`：将 Ocean consume 结果映射为 `TransactionRecord`。

Mesa/PySyft/Ocean 的 Agent、Domain、Datasite、asset 和 service 对象不会暴露给 DataValor
公共 API。区块链写入、远程执行和数据消费必须由调用方注入 client/executor，不会在
构造或导入阶段自动联网。

[返回模块索引](#module-index)

<a id="module-dataquery"></a>

## DataQuery：智能问数与数据智能体

源码入口：[src/datavalor/data_query](src/datavalor/data_query)

DataQuery 为获授权的用户或 Agent 提供可追溯的数据使用流程。授权在执行前校验，prompt 只承载用户意图。

### 标准执行链

```text
QueryRequest
  -> QueryAuthorizer
  -> QueryAuthorization
  -> QueryPlanner
  -> QueryPlan
  -> QueryExecutor
  -> raw QueryResult
  -> ResultGuard
  -> governed QueryResult
```

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `QueryAuthorizer` | `authorize` | 在执行前检查身份、用途、产品权利和政策 |
| `QueryPlanner` | `plan` | 把获批请求转换为可检查的 retrieval/computation 步骤 |
| `QueryExecutor` | `execute` | 执行计划并保留完整 trace |
| `ResultGuard` | `guard` | 应用行数限制、脱敏、聚合和结果政策 |
| `DataAgent` | `run` | 编排上述阶段并统一执行授权和结果防护 |

### 关键模型

`QueryRequest`、`QueryAuthorization`、`QueryPlanStep`、`QueryPlan`、`QueryTraceEvent`、`QueryResult`。

### 扩展 registry

`QUERY_AUTHORIZERS`、`QUERY_PLANNERS`、`QUERY_EXECUTORS`、`RESULT_GUARDS`、`DATA_AGENTS`。

DataQuery 的执行始终沿用 DataGov 的产品权利和授权结果，模型生成的 SQL 也需经过同一条执行链。未来 DB-GPT、数据库 connector 或 LLM 能力可通过这些接口接入。

### E5 外部 Query/Agent 适配器

`datavalor.data_query.backends` 已提供一条可组合的标准链路：

```text
RightsQueryAuthorizer
    -> DBGPTQueryPlanner / VannaQueryPlanner
    -> ExternalQueryExecutor
    -> QueryResultGuard
    -> GovernedDataAgent
```

- `RightsQueryAuthorizer`：依据产品 `RightsBundle.purposes` 和可选 policy callback 产生 `QueryAuthorization`；
- `DBGPTQueryPlanner`：封装 DB-GPT 的 `generate_sql`、`ask` 或 `generate` 入口；
- `VannaQueryPlanner`：封装 Vanna 的 `generate_sql`/`ask` 入口；
- `ExternalQueryExecutor`：把 `run_sql`、`execute` 或 `query` 结果转换为 `QueryResult`；
- `QueryResultGuard`：执行最大行数、字段脱敏和 truncation 标记；
- `GovernedDataAgent`：固定执行 `authorize → plan → execute → guard`，未授权时不会调用外部 agent。

DB-GPT/Vanna 的 SQL、DataFrame、agent state 和服务响应不会成为 DataValor 公共类型。
适配器支持注入 generator/client/executor，便于离线测试与多版本 SDK；真实包仅在执行时
通过 capability probe 加载。

[返回模块索引](#module-index)

<a id="module-toolkit"></a>

## Toolkit：跨模块公共工具

源码入口：[src/datavalor/toolkit](src/datavalor/toolkit)

Toolkit 为研究和应用层提供公共入口，当前重导出 `ArtifactEnvelope`、`ArtifactRef`、`ArtifactStore`、`PipelineNode`、`PipelineSpec`、`PipelineRunner`、`Registry` 和 `RunContext`。具体公共工具分为 Benchmark、Analysis 和 Web UI 三个子模块。

七个业务模块继续维护各自的结果语义，Toolkit 提供共享的 artifact、pipeline、benchmark、analysis 和 Web UI 工具。

[返回模块索引](#module-index)

<a id="module-benchmark"></a>

## Toolkit Benchmark：基准实验

源码入口：[src/datavalor/toolkit/benchmark](src/datavalor/toolkit/benchmark)

Benchmark 负责可复现地执行：

```text
component × case × repetition × metric
```

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `BenchmarkDataProvider` | `load` | 加载带 provenance 的真实、合成或缓存输入 |
| `DataPerturbation` | `apply` | 确定性构造 shift、noise、split 或 resampling |
| `BenchmarkMetric` | `measure` | 测量一次原始输出，聚合与排名由 benchmark 流程统一处理 |
| `BenchmarkRunner` | `run` | 执行 component、case、repetition 实验矩阵 |

关键模型为 `BenchmarkCase`、`BenchmarkSpec`、`BenchmarkObservation` 和 `BenchmarkReport`。原始 observation 与 aggregate 分开保存，方便复核每次实验并生成排行榜。

### 扩展 registry

`BENCHMARK_DATA_PROVIDERS`、`DATA_PERTURBATIONS`、`BENCHMARK_METRICS`、`BENCHMARK_RUNNERS`。

数据 provider、shift/扰动和 split 能力都放在这一层；市场 benchmark 与 pyDVL、OpenDataVal 等外部算法也通过同一套 benchmark 接口比较。

### E2 外部 Benchmark 数据源

`datavalor.toolkit.benchmark.backends.wilds.WILDSDataProvider` 使用 WILDS 的
`get_dataset` 和官方 `get_subset(split)`，将样本（包括 Tensor/array）转换为普通
Python records 后封装进 `ArtifactEnvelope`。默认不下载数据，可通过 case 参数显式开启；
也可以设置 `max_records` 或 `materialize=false` 控制物化范围。外部 Dataset 对象不会直接
成为 DataValor 公共 payload。

[返回模块索引](#module-index)

<a id="module-analysis"></a>

## Toolkit Analysis：统计分析与比较

源码入口：[src/datavalor/toolkit/analysis](src/datavalor/toolkit/analysis)

Analysis 消费已经落盘并带版本的 artifact，集中进行统计分析和方法比较；算法运行由 benchmark 或业务模块负责。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `Analyzer` | `analyze` | 生成统计量、warning 和派生产物 |
| `ResultComparator` | `compare` | 比较 baseline 与候选方法，保留 effect 和 uncertainty |
| `FrontierAnalyzer` | `frontier` | 在明确最大化/最小化方向和约束下计算 Pareto frontier |

关键模型为 `AnalysisRequest`、`AnalysisResult`、`ComparisonRequest` 和 `ComparisonResult`。

### 扩展 registry

`ANALYZERS`、`RESULT_COMPARATORS`、`FRONTIER_ANALYZERS`。

这一层提供市场策略、有限轮仿真、welfare/revenue benchmark、bootstrap、paired comparison 和 Pareto 分析。CLI、配置和插件加载入口位于 DataValor 自己的命名空间下。

[返回模块索引](#module-index)

<a id="module-webui"></a>

## Toolkit Web UI：可选交互层

源码入口：[src/datavalor/toolkit/webui](src/datavalor/toolkit/webui)

Web UI 保持 framework-neutral，核心包通过可选的 Streamlit、Gradio、FastAPI 等适配器接入，服务器按应用配置启动。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `ViewProvider` | `build` | 把 artifacts 转换为框架无关的 `ViewModel` |
| `WebApplicationFactory` | `create` | 把声明式 `ApplicationSpec` 和 view providers 转为具体应用对象 |

关键模型为 `ActionSpec`、`ViewSpec`、`ViewModel` 和 `ApplicationSpec`。

### 扩展 registry

`VIEW_PROVIDERS`、`WEB_APPLICATION_FACTORIES`。

Web UI 负责将公共接口转换为可交互的视图与操作，算法计算、治理决策和 artifact 存储仍由对应模块完成。

[返回模块索引](#module-index)

<a id="extension-example"></a>

## 最小扩展方式

下面用一个小例子演示接口与 registry 的使用方式：

```python
from datavalor import ComponentSpec, RunContext
from datavalor.core import DataProduct
from datavalor.data_eval import (
    EvaluationRequest,
    MetricResult,
    QUALITY_METRICS,
    QualityMetric,
    ScoreDirection,
)


class MyMetric(QualityMetric):
    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            name="example.my_metric",
            version="1.0.0",
            module="data_eval",
            kind="quality_metric",
            capabilities=("dataset",),
        )

    def compute(
        self,
        product: DataProduct,
        request: EvaluationRequest,
        context: RunContext,
    ) -> MetricResult:
        raise NotImplementedError


QUALITY_METRICS.register(MyMetric().spec, MyMetric)
metric = QUALITY_METRICS.create("example.my_metric")
```

正式实现应同时提交：

- 实现代码；
- 单元测试和性质测试；
- 最小配置与示例；
- `ComponentSpec` capability 和可选依赖；
- 算法来源、假设、复杂度和适用边界；
- 既有实现迁入时，需同步完成 DataValor 命名、接口、配置、产物和测试的改造，并将公共入口统一到 DataValor。

<a id="installation"></a>

## 安装与验证

基础安装保持轻量；开发环境可安装测试依赖：

```bash
python -m pip install -e ".[dev]"
python -c "from datavalor import MODULES; print([m.display_name for m in MODULES])"
pytest -q
ruff check src tests
```

统一主链路可以直接离线运行：

```bash
PYTHONPATH=src python examples/00_unified_value_chain.py
```

它使用 `configs/workflows/stage0_unified.json` 依次执行治理、画像、评估、估值、定价、市场、查询、使用计量和分析；每个阶段的 artifact 与运行摘要写入 `outputs/stage0-unified/`。

数据产品与质量基线可以单独运行：

```bash
PYTHONPATH=src python examples/05_stage1_governance_profile_eval.py
```

该示例读取含有重复、缺失值和类型错误的合成记录，生成元数据、权利决策、敏感字段发现、统计画像、版本差异和质量评估结果。

也可以用统一 runner 运行同一组治理、画像和评估步骤：

```bash
PYTHONPATH=src python examples/06_stage1_unified_workflow.py
```

入口加载 `configs/workflows/stage1_quality.json`，依次落盘治理 bundle、`DatasetProfile` 和 `EvaluationReport`。每个 artifact 都带父引用、schema version、运行参数和文件 checksum，可以继续交给 DataValue/DataPrice 使用。

任务相关估值和数据单元贡献分析：

```bash
PYTHONPATH=src python examples/07_stage2_task_valuation.py
```

入口加载 `configs/workflows/stage2_valuation.json`，复用治理、画像和质量评估结果，再由买方任务上下文驱动 `WeightedUserTaskValuator`，用 `TabularTaskUtility` 和 Monte Carlo Shapley 计算样本边际贡献。结果写入 `outputs/stage2-valuation/`；金额是给定 buyer/task/cost 假设下的价值估计，不是报价或支付。

高级估值与贡献分摊：

```bash
PYTHONPATH=src python examples/08_stage3_advanced_valuation.py
```

入口追加安全符号估值、线性模型训练/预测、精确 Shapley 和贡献金额分摊，结果写入 `outputs/stage3-valuation/`。

按需启用外部治理 connector：

```bash
python -m pip install -e ".[governance]"
python -m pip install -e ".[simulation]"  # Mesa
python -m pip install -e ".[market]"      # Ocean.py/ocean-lib
python -m pip install -e ".[query]"        # DB-GPT/Vanna
```

该 extra 包含 DataHub、OpenMetadata 和 PyDeequ SDK；Spark 集群、DataHub/OpenMetadata
服务地址和凭据仍由部署环境注入，DataValor 不会在安装或导入时自动连接这些服务。

测试目前覆盖：

- 所有公共模块在可选依赖缺席时仍可导入；
- 所有扩展接口均采用需要具体实现才能实例化的 ABC；
- registry 的延迟 factory、重名保护和 freeze；
- artifact、evaluation、valuation、pricing 的语义边界；
- 货币金额使用 `Decimal`；
- `src/datavalor` 不导入 `dvmk`。

<a id="documentation"></a>

## 文档与调研资料

- [架构与模块契约](docs/architecture.md)
- [系统框架与接口设计](docs/interfaces.md)
- [GitHub 项目调研与选型](docs/research/github_landscape.md)
- [机器可读参考项目清单](docs/research/reference_projects.yaml)
- [外部仓库功能复用规划](docs/research/external_repo_reuse_plan.md)
- [外部仓库复用阶段配置](configs/integrations/external_repo_reuse.yaml)
- [data_value_market_kit 代码筛选、迁移与改造方案](docs/research/dvmk_reuse.md)
- [数据估值定价调研与 DataValor 能力地图](docs/research/data_valuation_pricing_landscape.md)
- [阶段 1：数据产品、治理、画像与质量评估实现说明](docs/research/stage1_data_product_governance.md)
- [阶段 2：任务效用、估值与数据单元贡献实现说明](docs/research/stage2_data_valuation.md)
- [阶段 3：符号估值、学习型估值与贡献分摊实现说明](docs/research/stage3_advanced_valuation.md)
- [DataValue 风险、反事实、组合与校准扩展](docs/research/datavalue_extensions.md)
- [DVMK 源码迁移执行手册](docs/migrations/dvmk/README.md)
- [机器可读 DVMK 迁移计划](configs/migrations/dvmk/plan.yaml)

参考项目用于记录调研依据和后续选型方向。仓库尚未迁移这些项目的代码、模型或数据，正式接入前会复核版本、许可证、数据权利与安全边界。

可选依赖边界、DataEval/DataProf 适配器、DataValue/Benchmark 适配器、DataGov connector、DataMarket/Simulation connector 和 DataQuery connector 均有对应实现。第三方依赖不进入基础安装，适配器输出统一转换为 DataValor 公共模型。

DVMK 是实验室已有的代码基础，相关实现会迁入并重构为 `datavalor.*` 原生代码。迁入后由 DataValor 独立维护，公共入口使用 DataValor 的命名和协议。

<a id="development-principles"></a>

## 开发原则

- 质量评估、估值与定价保持各自语义层，价格计算引用明确的估值和市场证据；
- 算法通过稳定协议和 registry 接入，benchmark 与算法实现解耦；
- 运行产物包含 schema version、配置、随机种子、依赖版本、输入摘要和 provenance；
- 一般外部能力优先采用 optional dependency、adapter、API 或服务边界；实验室自有实现可以完整迁入，但必须按 DataValor 接口和目录重构；
- DVMK 的完整实现文件迁入后成为 `datavalor.*` 原生实现，统一采用 DataValor 的包名、protocol、CLI 命令和路径；
- 重型依赖不在公共包 import 阶段加载；
- 算法层通过协议连接输出目录、数据库、Web 框架或 UI；
- 原始数据、受限数据和大体积输出默认不提交到 Git。

## License

Apache License 2.0。数据、模型和可选依赖按实际使用范围管理；实验室自有实现统一遵循 DataValor 的目录、接口和发布约定。
