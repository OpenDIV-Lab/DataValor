# DataValor 系统框架与接口设计

> 状态：`v1alpha1 interface scaffold`。本文定义可实现、可注册、可测试的接口模板，不包含具体数据治理、估值、定价或智能问数算法。

## 一、结构参考来源

本框架只参考调研项目的**工程组织方式**，没有复制其算法内容或接口源码：

| 结构来源 | 借鉴的结构模式 | DataValor 中的体现 |
|---|---|---|
| pyDVL | 明确的数据、utility、valuation method、result 和 fit 生命周期 | `UtilityFunction`、`DataValuator`、`TrainableValuator`、`ValuationReport` |
| OpenDataVal | data loader、dataval、experiment、metric 分层 | DataValue 与 `toolkit.benchmark` 分离，算法不直接承担 benchmark 编排 |
| TorchMetrics | 小型 metric 基类、metric collection、状态/证据和可选领域依赖 | `QualityMetric`、`MetricResult`、`DataEvaluator` 和 typed registry |
| Cleanlab、Great Expectations、Evidently | finding、evidence、validation/report 与执行编排分离 | `GovernanceFinding`、`Evidence`、`EvaluationReport`、`GovernanceReport` |
| Kedro | catalog、节点、pipeline、artifact/config 边界 | `MetadataCatalog`、`PipelineNode`、`PipelineSpec`、`ArtifactEnvelope` |
| Mesa | participant、strategy、observation、state、step、data collection 分层 | `ParticipantStrategy`、`MarketObservation`、`SimulationStep`、`MarketSimulator` |
| DataHub、OpenMetadata | 元数据与治理平台通过稳定边界连接，而不是塞进算法包 | `MetadataRecord`、`MetadataCatalog`、`PolicyEvaluator` |

DVMK 与一般第三方项目不同。它是后续选择性迁移的内部代码来源；迁移内容必须实现本文接口并成为 `datavalor.*` 原生代码，而不是在这些接口内部调用 `dvmk`。

## 二、代码结构

```text
src/datavalor/
├── core/
│   ├── component.py             # ComponentSpec、Component、BaseComponent
│   ├── context.py               # RunContext
│   ├── models.py                # DataReference、DataProduct、ActorProfile 等
│   ├── artifact.py              # ArtifactEnvelope、ArtifactRef、Evidence
│   ├── registry.py              # typed lazy Registry
│   ├── pipeline.py              # PipelineNode、PipelineSpec、PipelineRunner
│   ├── interfaces.py            # ArtifactStore
│   └── exceptions.py
├── data_gov/                    # models.py、interfaces.py、registry.py
├── data_prof/                   # models.py、interfaces.py、registry.py
├── data_eval/                   # models.py、interfaces.py、registry.py
├── data_value/                  # models.py、interfaces.py、registry.py
├── data_market/
│   ├── models.py、interfaces.py、registry.py
│   └── simulation/              # observation、strategy、step、simulator
├── data_price/                  # quote、bid、ask、allocation、payment
├── data_query/                  # authorize、plan、execute、guard、agent
└── toolkit/
    ├── benchmark/               # provider、perturbation、metric、runner
    ├── analysis/                # analyzer、comparator、frontier
    └── webui/                   # framework-neutral view/app factory
```

每个业务模块都遵循同一种目录约定：

- `models.py`：跨实现稳定传递的 request、result、finding 和 report；
- `interfaces.py`：只声明行为和语义边界的 ABC；
- `registry.py`：按能力分类的 typed lazy registry；
- `__init__.py`：经过选择的公共 API，不暴露内部实现路径。

具体算法加入后可以继续建立 `metrics/`、`valuators/`、`mechanisms/`、`providers/` 等实现目录，但不能反向污染公共模型。

## 三、公共接口

### 1. `ComponentSpec` 与 `BaseComponent`

所有可注册实现都必须提供：

```python
ComponentSpec(
    name="data_eval.example_metric",
    version="1.0.0",
    module="data_eval",
    kind="quality_metric",
    capabilities=("dataset", "tabular"),
    requires=("example-extra",),
)
```

这些元数据用于组件发现、能力检查、artifact provenance 和 benchmark 记录。组件名称必须是稳定标识，不使用 Python 类名充当实验协议。

### 2. `RunContext`

`RunContext` 显式传递：

- `run_id` 和随机种子；
- 调用方 `actor_id` 与任务 `task_id`；
- 权利包 `RightsBundle`；
- 模块配置、标签和附加元数据；
- 运行开始时间。

算法不能从全局变量、固定目录或隐式环境中猜测这些信息。

### 3. `ArtifactEnvelope[T]`

模块间通过有版本的产物信封连接：

```text
artifact_id + kind + schema_version
producer ComponentSpec
payload T
status
parent ArtifactRef[]
evidence[]
diagnostics
created_at
```

原生 payload 保留具体类型，例如 `EvaluationReport` 或 `PricingOutcome`；信封只统一 provenance 和 lineage，不把所有结果压成一个字典或单一分数。

### 4. `Registry[T]`

Registry 接收 `ComponentSpec + factory`，只有在 `create(name)` 时才实例化组件，因此重型可选依赖不应在 `import datavalor` 时加载。Registry 支持：

- 重名保护和显式 `replace`；
- 不实例化组件即可读取 `ComponentSpec`；
- 稳定排序的 `names()` 和 `specs()`；
- benchmark 运行前 `freeze()`，防止实验过程中组件集合变化。

### 5. Pipeline 与 ArtifactStore

`PipelineSpec` 只声明节点、输入引用、输出名和参数；`PipelineRunner` 负责校验和执行；`ArtifactStore` 负责保存与加载。算法接口本身不直接创建固定的 `outputs/...` 目录。

## 四、七个业务模块的具体接口

### 1. DataGov

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `MetadataExtractor` | `inspect(product, context)` | 提取技术、语义、权利和血缘元数据 |
| `MetadataCatalog` | `upsert/get/search` | 保存和发现可见的治理元数据 |
| `DataStandardizer` | `plan/transform` | 先生成可审计计划，再执行标准化 |
| `DataCleaner` | `plan/clean` | 先生成清洗计划，再物化新数据引用 |
| `SecurityScanner` | `scan` | 发现敏感字段、泄露和安全风险 |
| `PolicyEvaluator` | `evaluate` | 对具体 operation 返回 allow/deny/review |

重要输出包括 `MetadataRecord`、`TransformationPlan`、`TransformationResult`、`SecurityReport` 和 `GovernanceReport`。

### 2. DataProf

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `ProfileMetric` | `measure` | 计算一个描述性事实，不判断好坏 |
| `DataProfiler` | `profile` | 组合统计量形成 `DatasetProfile` |
| `ProfileComparator` | `compare` | 比较两个 profile 的描述性变化 |

`DatasetProfile` 不包含最终质量结论；分布变化是否不可接受，由 DataEval 的具体 metric 或 policy 判断。

### 3. DataEval

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `QualityMetric` | `compute` | 在明确粒度上计算一个质量指标 |
| `DataEvaluator` | `evaluate` | 组合多个 metric，保留各自证据 |
| `TaskUtilityEvaluator` | `evaluate_task` | 通过下游任务实验测量实际 utility |

`MetricResult` 明确包含 dimension、scope、value、direction、unit、statistics、evidence 和 diagnostics。`EvaluationReport` 不是 DataValue，也不是 DataPrice。

### 4. DataValue

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `UtilityFunction` | `score` | 评估一个数据子集对任务的 utility |
| `DataValuator` | `value` | 对 sample/group/dataset/product 估值 |
| `TrainableValuator` | `fit/value` | 从历史观测学习估值模型 |
| `ContributionValuator` | `value_contributions` | 计算边际或联盟贡献度 |

`ValuationRequest` 显式携带 buyer、task、rights、costs 和 evaluation artifacts；`ValueEstimate` 显式携带 unit、currency、components、uncertainty 和 explanation。它仍然不是市场 bid。

### 5. DataPrice

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `PricingModel` | `quote` | 给出产品、买方、任务和权利相关 quote |
| `OnlinePricingModel` | `quote/observe` | 使用完整曝光和成交日志更新状态 |
| `PriceConstraint` | `project` | 执行 no-arbitrage 等价格约束 |
| `PricingMechanism` | `price` | 从 bids、asks、supply、demand 计算 allocation/payment |

金额统一使用 `Decimal` 封装在 `Money` 中。`Bid` 是报告的支付意愿，`ValueEstimate` 是估计价值，`PriceQuote` 是报价，`Payment` 是机制结果，四者不能混用。

### 6. DataMarket

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `MarketCatalog` | `publish/withdraw/discover` | 数据产品注册、下架和发现 |
| `ParticipantRepository` | `upsert/get/search` | 管理模拟和机制需要的最小参与者画像 |
| `IncentivePolicy` | `compute` | 在价格之外计算参与激励 |
| `RevenueAllocator` | `allocate` | 按贡献和规则分配已实现收入 |
| `TransactionProcessor` | `execute` | 定价后执行权利、交付和结算 |
| `ParticipantStrategy` | `decide/observe` | 市场参与者决策与状态更新 |
| `MarketSimulator` | `reset/step/run` | 组织有限轮市场实验 |

职责边界是：DataPrice 计算 quote、allocation 和 payment；DataMarket 管理 listing、participant、transaction、incentive、revenue allocation 和 simulation。

### 7. DataQuery

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `QueryAuthorizer` | `authorize` | 在执行前检查身份、用途、权利和政策 |
| `QueryPlanner` | `plan` | 把获批请求转换为可检查步骤 |
| `QueryExecutor` | `execute` | 执行计划并保留完整 trace |
| `ResultGuard` | `guard` | 对结果执行行数限制、脱敏和聚合 |
| `DataAgent` | `run` | 编排上述阶段，不绕过政策门 |

`QueryAuthorization` 是执行前置条件。`QueryResult.trace` 应记录 planning、execution 和 guarding 发生的实际变化。

## 五、Toolkit 接口

### Benchmark

| 接口 | 主要方法 | 职责 |
|---|---|---|
| `BenchmarkDataProvider` | `load` | 加载带 provenance 的真实或合成输入 |
| `DataPerturbation` | `apply` | 确定性构造 shift、noise、split 或重采样 |
| `BenchmarkMetric` | `measure` | 测量一次原始输出，不负责排行榜聚合 |
| `BenchmarkRunner` | `run` | 执行 component × case × repetition 矩阵 |

### Analysis

- `Analyzer.analyze`：通用统计与派生产物；
- `ResultComparator.compare`：基准方法与候选方法比较；
- `FrontierAnalyzer.frontier`：带明确目标方向和约束的 Pareto frontier。

### Web UI

Web UI 接口保持 framework-neutral：`ViewProvider` 只把 artifacts 转成 `ViewModel`，`WebApplicationFactory` 再把声明式 `ApplicationSpec` 转成 Streamlit、FastAPI、Gradio 或其他具体对象。核心包不会启动服务器，也不依赖任何 Web 框架。

## 六、最小扩展示例

下面的实现只展示接口使用方式，不是内置算法：

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
    def spec(self):
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

正式实现需要同时提交：组件实现、测试、配置示例、方法说明、依赖 extra，以及包含假设和边界的文档。

## 七、当前非目标

本轮没有实现：

- 实际清洗、画像、质量指标或估值算法；
- 拍卖、采购、动态定价和收益分配算法；
- 数据库、对象存储、DataHub 或 OpenMetadata connector；
- Text-to-SQL、LLM agent 或 Web UI；
- DVMK 源码迁移。

这些能力后续都应在当前接口上逐项实现和验证，而不是绕过接口直接堆叠脚本。
