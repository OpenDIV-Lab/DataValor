# DataValor

**A Toolkit for Data Valorization**

数据智能与价值化实验室（Data Intelligence and Valorization Laboratory，DIV Lab）发起的开源研究工具箱。

> 当前状态：`pre-alpha / interface scaffold`。本仓库目前定义模块边界、公共模型、抽象接口、registry、benchmark 和扩展路线，不代表各模块已经具有具体算法或生产能力。

DataValor 面向数据从“可管理”到“可使用、可交易、可定价”的完整价值链，将研究对象分成三个阶段：

1. **价值发现（Value Discovery）**：DataGov、DataProf、DataEval、DataValue；
2. **价值流通（Value Circulation）**：DataMarket、DataPrice；
3. **价值实现（Value Realization）**：DataQuery。

<a id="module-index"></a>

## 模块索引

下面的索引使用显式英文锚点，不依赖 Markdown 渲染器自动生成中文标题 ID，可从 GitHub 或 IDE 预览稳定跳转。

| 阶段 | 模块 | 核心职责 | 详细说明 |
|---|---|---|---|
| 公共基础 | `datavalor.core` | 组件、数据产品、运行上下文、产物、registry、pipeline、存储协议 | [Core](#module-core) |
| 价值发现 | `datavalor.data_gov` | 标准化、清洗、安全、元数据、政策和治理 | [DataGov](#module-datagov) |
| 价值发现 | `datavalor.data_prof` | 统计画像、字段属性、分布和画像比较 | [DataProf](#module-dataprof) |
| 价值发现 | `datavalor.data_eval` | 多维质量评估、证据和任务效用测量 | [DataEval](#module-dataeval) |
| 价值发现 | `datavalor.data_value` | 用户/任务相关估值和数据贡献度 | [DataValue](#module-datavalue) |
| 价值流通 | `datavalor.data_market` | 挂牌、发现、参与者、激励、交易、收益分配和仿真 | [DataMarket](#module-datamarket) |
| 价值流通 | `datavalor.data_price` | 报价、动态定价、拍卖清算、allocation 和 payment | [DataPrice](#module-dataprice) |
| 价值实现 | `datavalor.data_query` | 授权、查询规划、执行、结果防护和数据智能体 | [DataQuery](#module-dataquery) |
| 公共工具 | `datavalor.toolkit` | 对公共 artifact、pipeline、registry 的便捷导出 | [Toolkit](#module-toolkit) |
| 公共工具 | `datavalor.toolkit.benchmark` | 数据源、扰动、benchmark metric 和实验矩阵 | [Benchmark](#module-benchmark) |
| 公共工具 | `datavalor.toolkit.analysis` | 统计分析、方法比较和 Pareto frontier | [Analysis](#module-analysis) |
| 公共工具 | `datavalor.toolkit.webui` | 与具体 Web 框架无关的 view/app 接口 | [Web UI](#module-webui) |

其他常用位置：

- [仓库结构](#repository-layout)
- [模块间语义边界](#semantic-boundaries)
- [最小扩展方式](#extension-example)
- [安装与验证](#installation)
- [文档与调研资料](#documentation)
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

目录采用 Python 可导入命名。例如方案中的 `DataValue` 对应 `datavalor.data_value`；展示顺序和阶段信息可从 `datavalor.MODULES` 读取。没有采用 `0_DataGov` 作为包名，因为数字开头不能成为正常的 Python import 路径。

每个业务模块默认采用相同的内部约定：

```text
module/
├── models.py       # 稳定的 request、result、finding、report
├── interfaces.py   # 不包含算法实现的抽象接口
├── registry.py     # 按能力分类的 typed lazy registry
└── __init__.py     # 经过筛选的公共 API
```

未来具体实现可以放入 `metrics/`、`valuators/`、`mechanisms/`、`providers/` 等子目录，但不应反向改变公共模型的语义。

<a id="semantic-boundaries"></a>

## 模块间语义边界

DataValor 不把整个数据价值链压成一个“综合分数”。各模块通过有版本的 artifact 连接：

```text
DataGov 治理与可用性
  -> DataProf 描述性事实
  -> DataEval 质量与任务表现
  -> DataValue 用户/任务相关效用或贡献
  -> DataPrice quote、allocation 与 payment
  -> DataMarket 交易、激励和收入分配
  -> DataQuery 受治理的数据使用与结果
```

必须保持以下区分：

- profile 是描述性事实，不是质量结论；
- evaluation 是多维质量或任务表现，不是货币价值；
- valuation 是效用或贡献估计，不是买方 bid；
- bid 是报告的支付意愿，不是平台 quote；
- quote 是报出的价格，不是最终 payment；
- payment 是机制和市场环境共同产生的交易结果；
- simulation observation 不是均衡、真实性或最优性的理论证明；
- query answer 只有在授权、执行和结果防护全部完成后才是可交付结果。

<a id="module-core"></a>

## Core：公共契约与基础设施

源码入口：[src/datavalor/core](src/datavalor/core)

Core 是所有模块共享的零第三方依赖基础层。它只定义跨模块稳定概念，不实现清洗、估值、拍卖或问数算法。

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

Core 不负责：打开数据 URI、执行数据库查询、决定治理政策、运行算法或创建固定 `outputs/` 路径。

[返回模块索引](#module-index)

<a id="module-datagov"></a>

## DataGov：数据治理

源码入口：[src/datavalor/data_gov](src/datavalor/data_gov)

DataGov 回答“这份数据是否有明确来源、元数据、权利和处理规则，以及某项操作是否允许执行”。它覆盖标准化、清洗、安全、元数据和政策决策，但当前只是接口模板，不等同于完整的数据目录或合规平台。

### 主要输入与输出

- 输入：`DataProduct`、`StandardDefinition`、治理规则、operation、`RunContext`；
- 输出：`MetadataRecord`、`TransformationPlan`、`TransformationResult`、`SecurityReport`、`GovernanceReport`。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `MetadataExtractor` | `inspect(product, context)` | 提取技术、语义、权利、分类和血缘元数据 |
| `MetadataCatalog` | `upsert/get/search` | 保存并检索治理元数据，不绑定 DataHub/OpenMetadata |
| `DataStandardizer` | `plan/transform` | 先产生可审计计划，再执行格式、schema 或语义标准化 |
| `DataCleaner` | `plan/clean` | 先产生清洗计划，再物化新的数据引用 |
| `SecurityScanner` | `scan` | 检测敏感字段、泄露、隐私和安全风险 |
| `PolicyEvaluator` | `evaluate` | 针对具体 operation 返回 allow、deny 或 review |

### 关键模型

`FieldSchema`、`MetadataRecord`、`GovernanceFinding`、`GovernanceReport`、`StandardDefinition`、`TransformationStep`、`TransformationPlan`、`TransformationResult`、`SecurityReport`、`CatalogQuery`。

### 扩展 registry

`METADATA_EXTRACTORS`、`METADATA_CATALOGS`、`STANDARDIZERS`、`CLEANERS`、`SECURITY_SCANNERS`、`POLICY_EVALUATORS`。

DataGov 不负责：把 provenance manifest 宣称为完整合规认证，也不负责统计画像、质量打分、估值或价格计算。

[返回模块索引](#module-index)

<a id="module-dataprof"></a>

## DataProf：数据画像

源码入口：[src/datavalor/data_prof](src/datavalor/data_prof)

DataProf 回答“数据是什么样的”。它生成字段类型、缺失、基数、分布和数据集级属性，并支持不同时间或数据版本之间的画像比较。

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

DataProf 不负责：判断某个分布是否“好”、把 drift 直接认定为质量问题、生成货币估值。是否可接受由 DataEval metric 或 DataGov policy 决定。

[返回模块索引](#module-index)

<a id="module-dataeval"></a>

## DataEval：数据质量评估

源码入口：[src/datavalor/data_eval](src/datavalor/data_eval)

DataEval 回答“数据在明确维度、粒度和任务下表现如何”。它保留每个指标的方向、单位、统计量、证据和诊断，不把所有指标静默合成一个货币分数。

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

DataEval 不负责：直接生成 buyer-specific value、bid、quote 或 payment。未来从 DVMK 迁移的多模态指标和 task utility 应在此实现。

[返回模块索引](#module-index)

<a id="module-datavalue"></a>

## DataValue：数据估值与贡献度

源码入口：[src/datavalor/data_value](src/datavalor/data_value)

DataValue 回答“这份数据或其中某个单位对特定用户、任务或模型的效用与贡献是多少”。估值对象可以是 sample、group、dataset 或 data product。

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

DataValue 不负责：把价值估计当作真实 bid，或根据供需直接产生交易价格。未来 DVMK 的 weighted user-task、learned/symbolic valuation、LOO、Shapley 和 Banzhaf 实现应迁入此模块。

[返回模块索引](#module-index)

<a id="module-dataprice"></a>

## DataPrice：数据定价与机制计算

源码入口：[src/datavalor/data_price](src/datavalor/data_price)

DataPrice 回答“在给定估值证据、权利、报价、供需和机制规则下，应给出什么 quote，以及如何计算 allocation 和 payment”。所有货币金额使用 `Decimal` 封装在 `Money` 中。

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

DataPrice 不负责：listing 生命周期、参与者数据库、数据交付和结算执行。未来 DVMK 的 VCG、McAfee、posted price、procurement、core-selecting 和 contextual-bandit pricing 应迁入此模块。

[返回模块索引](#module-index)

<a id="module-datamarket"></a>

## DataMarket：数据市场与市场仿真

源码入口：[src/datavalor/data_market](src/datavalor/data_market)

DataMarket 回答“数据产品如何注册和发现，市场参与者如何行动，定价结果如何转化为交易、激励和收入分配”。它消费 DataPrice 的 `PricingOutcome`，但不重新定义第二套价格、allocation 或 payment 对象。

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

仿真模型包括 `MarketObservation`、`StrategyDecision`、`SimulationStep` 和 `SimulationReport`。仿真结果默认只是实验观察，不自动声称 equilibrium、no-regret 或 incentive compatibility。

### 扩展 registry

`MARKET_CATALOGS`、`PARTICIPANT_REPOSITORIES`、`INCENTIVE_POLICIES`、`REVENUE_ALLOCATORS`、`TRANSACTION_PROCESSORS`、`PARTICIPANT_STRATEGIES`、`MARKET_SIMULATORS`。

DataMarket 不负责：计算指标质量或内生估值，也不自行实现另一套货币类型和支付 schema。

[返回模块索引](#module-index)

<a id="module-dataquery"></a>

## DataQuery：智能问数与数据智能体

源码入口：[src/datavalor/data_query](src/datavalor/data_query)

DataQuery 回答“获授权用户或 Agent 如何安全地使用数据并获得可追溯结果”。授权是执行前的硬接口，不是 prompt 中的一句文字。

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
| `DataAgent` | `run` | 编排上述阶段，但不能绕过授权和结果防护 |

### 关键模型

`QueryRequest`、`QueryAuthorization`、`QueryPlanStep`、`QueryPlan`、`QueryTraceEvent`、`QueryResult`。

### 扩展 registry

`QUERY_AUTHORIZERS`、`QUERY_PLANNERS`、`QUERY_EXECUTORS`、`RESULT_GUARDS`、`DATA_AGENTS`。

DataQuery 不负责：绕过 DataGov 的产品权利或把模型生成的 SQL 直接视为已授权查询。未来 DB-GPT、数据库 connector 或 LLM 能力应通过这些接口接入。

[返回模块索引](#module-index)

<a id="module-toolkit"></a>

## Toolkit：跨模块公共工具

源码入口：[src/datavalor/toolkit](src/datavalor/toolkit)

Toolkit 为研究和应用层提供公共入口，当前重导出 `ArtifactEnvelope`、`ArtifactRef`、`ArtifactStore`、`PipelineNode`、`PipelineSpec`、`PipelineRunner`、`Registry` 和 `RunContext`。具体公共工具分为 Benchmark、Analysis 和 Web UI 三个子模块。

Toolkit 不负责：重新定义七个业务模块的结果语义，也不允许 benchmark runner 直接成为算法公共 API。

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
| `BenchmarkMetric` | `measure` | 测量一次原始输出，不负责排行榜聚合 |
| `BenchmarkRunner` | `run` | 执行 component、case、repetition 实验矩阵 |

关键模型为 `BenchmarkCase`、`BenchmarkSpec`、`BenchmarkObservation` 和 `BenchmarkReport`。原始 observation 与 aggregate 分开保存，不能只保留最终排行榜。

### 扩展 registry

`BENCHMARK_DATA_PROVIDERS`、`DATA_PERTURBATIONS`、`BENCHMARK_METRICS`、`BENCHMARK_RUNNERS`。

未来 DVMK 的 distribution provider、shift transform 和 market benchmark 应在此拆分迁入；pyDVL、OpenDataVal 等外部算法也通过统一 benchmark 比较。

[返回模块索引](#module-index)

<a id="module-analysis"></a>

## Toolkit Analysis：统计分析与比较

源码入口：[src/datavalor/toolkit/analysis](src/datavalor/toolkit/analysis)

Analysis 消费已经落盘并带版本的 artifact，负责统计分析和方法比较，不负责重新运行被分析算法。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `Analyzer` | `analyze` | 生成统计量、warning 和派生产物 |
| `ResultComparator` | `compare` | 比较 baseline 与候选方法，保留 effect 和 uncertainty |
| `FrontierAnalyzer` | `frontier` | 在明确最大化/最小化方向和约束下计算 Pareto frontier |

关键模型为 `AnalysisRequest`、`AnalysisResult`、`ComparisonRequest` 和 `ComparisonResult`。

### 扩展 registry

`ANALYZERS`、`RESULT_COMPARATORS`、`FRONTIER_ANALYZERS`。

未来 DVMK 的 paired bootstrap、统计汇总、failure witness 和 Pareto 分析可以按这些接口迁入。

[返回模块索引](#module-index)

<a id="module-webui"></a>

## Toolkit Web UI：可选交互层

源码入口：[src/datavalor/toolkit/webui](src/datavalor/toolkit/webui)

Web UI 保持 framework-neutral，核心包不依赖 Streamlit、Gradio、FastAPI 或其他具体框架，也不会在 import 时启动服务器。

### 具体接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `ViewProvider` | `build` | 把 artifacts 转换为框架无关的 `ViewModel` |
| `WebApplicationFactory` | `create` | 把声明式 `ApplicationSpec` 和 view providers 转为具体应用对象 |

关键模型为 `ActionSpec`、`ViewSpec`、`ViewModel` 和 `ApplicationSpec`。

### 扩展 registry

`VIEW_PROVIDERS`、`WEB_APPLICATION_FACTORIES`。

Web UI 不负责：算法计算、治理决策和 artifact 存储；它只展示或触发已经通过公共接口声明的能力。

[返回模块索引](#module-index)

<a id="extension-example"></a>

## 最小扩展方式

下面只演示接口与 registry 的使用，不是内置质量算法：

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
- 如果由 DVMK 迁移，提交源 revision、源路径、MIT 归属和改造记录。

<a id="installation"></a>

## 安装与验证

仓库当前没有运行时依赖；开发环境可安装轻量测试依赖：

```bash
python -m pip install -e ".[dev]"
python -c "from datavalor import MODULES; print([m.display_name for m in MODULES])"
pytest -q
ruff check src tests
```

当前契约测试覆盖：

- 所有公共模块在没有可选依赖时可导入；
- 所有扩展接口都是不能直接实例化的 ABC；
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
- [data_value_market_kit 代码筛选、迁移与改造方案](docs/research/dvmk_reuse.md)

参考项目只作为调研对象列出，不表示 DIV Lab 或 DataValor 对其背书。仓库当前尚未迁移这些项目的代码、模型或数据；真正接入前仍需复核版本、许可证、数据权利与安全边界。

DVMK 是实验室已有代码基础，将采用“筛选源码、保留 MIT 归属、按 DataValor 模块重构后直接纳入”的方式迁移，而不是作为运行时依赖调用。

<a id="development-principles"></a>

## 开发原则

- 质量评估、估值与定价是不同语义层，不把质量分数直接当作价格；
- 算法通过稳定协议和 registry 接入，benchmark 与算法实现解耦；
- 运行产物包含 schema version、配置、随机种子、依赖版本、输入摘要和 provenance；
- 一般第三方能力优先采用 optional dependency、adapter、API 或服务边界，不直接复制研究仓库源码；
- DVMK 作为已有内部代码基础按文件和算法选择性迁移，迁移后成为 `datavalor.*` 原生实现，并保留完整来源、许可证和改造记录；
- 重型依赖不在公共包 import 阶段加载；
- 算法层不直接绑定固定输出目录、数据库、Web 框架或 UI；
- 原始数据、受限数据和大体积输出默认不提交到 Git。

## License

Apache License 2.0。第三方依赖和数据保持各自的许可证与使用条款；从 DVMK 迁移的实质性代码必须继续保留其 MIT 版权和许可声明。
