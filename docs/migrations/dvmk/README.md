# DVMK 源码迁移执行手册

本目录描述如何把 `/root/yusen/data_value_market_kit` 中的完整实现文件复制、改造并融入 DataValor，目标是形成可独立维护的原生模块。

机器可读总计划：[configs/migrations/dvmk/plan.yaml](../../../configs/migrations/dvmk/plan.yaml)

当前进度：Stage 0–5 以及 Stage 6（DataValor 原生 CLI、配置、示例与插件）均已完成；对应实现已经落位到 `src/datavalor`，本文作为过程记录继续保留。

## 1. 迁移原则

1. DVMK 目录中的完整实现文件是迁移输入，DataValor 是唯一最终运行项目。
2. 完整迁移不等于原样保留：每个文件都必须改成 DataValor 的目录、命名、接口、配置和产物 schema。
3. 迁移后的目标代码统一使用 `datavalor.*`，并完成源项目命名到 DataValor 命名的转换。
4. CLI、输出路径、配置协议和 runner 在 DataValor 中重新接入，形成新的公共 API。
5. 每批迁移必须同时提交目标代码、改造后的测试、配置示例和文档，并通过源残留扫描。
6. 迁移以当前工作区完整文件为准，不做版本筛选、增量兼容或双版本适配。

## 2. DVMK 实际内容盘点与目标接口

### 2.1 公共基础、数据产品和数据源

DVMK 已实现：JSONL/JSON/CSV/Parquet/目录/iterable 适配器、canonical record hash、文件 SHA-256、运行元数据、artifact 写入、local/parametric/sklearn/Hugging Face provider，以及 label shift、covariate shift、missingness、noise、duplicate、group/time split 等变换。

迁移目标：

| 源实现内容 | DataValor 目标接口 | 具体改造 |
|---|---|---|
| `file_sha256`、`canonical_sha256`、I/O | `datavalor.core.ArtifactStore` | 去掉固定输出目录，返回 `ArtifactRef`，把 checksum 和 lineage 放进 `ArtifactEnvelope` |
| `JSONLAdapter`、`CSVAdapter`、`ParquetAdapter`、`DirectoryAdapter` | `data_gov` 数据产品实现 | 保留流式读取，增加 rights、schema、classification 和 owner 元数据 |
| distribution manifest | `ArtifactEnvelope` + `MetadataRecord` | 区分治理 manifest 和 benchmark distribution manifest |
| local/parametric/sklearn/HF providers | `BenchmarkDataProvider` | 作为研究输入 provider，和 DataGov 的治理能力分开 |
| shift/noise/split/重采样 | `DataPerturbation` | 每次输出 parent、seed、参数和变换审计 |

### 2.2 DataProf 与 DataEval

DVMK 已实现：统一 `MetricResult`/metric registry；文本 lexical diversity；图像/音频 metadata quality；多模态 package integrity；Cleanlab label quality；embedding MMD；LiteLLM semantic judge；task contribution；sklearn classification/regression utility；视频 metadata、format、motion、cleanliness、segmentation、temporal consistency 和 privacy 风险算子；score artifact 写入。

迁移目标：

| DVMK 内容 | DataValor 目标接口 | 具体改造 |
|---|---|---|
| `BaseMetric`、`MetricResult`、score artifact writer | `QualityMetric` + `MetricResult` | 增加 scope、direction、unit、evidence、diagnostics，拆开画像事实和质量判断 |
| lexical/image/audio/multimodal 指标 | `QualityMetric` | 规范方向、粒度、范围和缺失行为 |
| Cleanlab/MMD/LiteLLM | `QualityMetric` | 作为 optional extras，保留样本级证据，依赖延迟加载 |
| task utility、cache、sklearn tasks | `TaskUtilityEvaluator` | 明确 `TaskContext` 和观测 utility，不产生货币价值 |
| 视频 helper 和 CV 指标 | `QualityMetric` | 隔离 OpenCV/ffprobe，文件不可用时给出显式 diagnostics |
| 基础统计与字段属性 | `ProfileMetric`/`DataProfiler` | 输出 `DatasetProfile`，质量结论交由 DataEval 结合场景判断 |

### 2.3 DataValue

DVMK 已实现：多格式 requirements 导入、列名映射、点号字段展开、覆盖合并；LOO、exact Shapley、Monte Carlo Shapley、Banzhaf；weighted user-task、distribution preview、contribution-adjusted；learned linear、restricted expression、reflective symbolic；表达式校验、求值、反思历史、单调性和复杂度约束。

迁移目标：

| DVMK 内容 | DataValor 目标接口 | 具体改造 |
|---|---|---|
| requirements 导入与合并 | `ValuationRequest` | 映射为 typed buyer/task/rights/cost context，保留覆盖规则 |
| `leave_one_out`、`exact_shapley`、`monte_carlo_shapley`、`banzhaf` | `ContributionValuator` | 暴露 scope、utility calls、预算、收敛和不确定性 |
| weighted/distribution/contribution-adjusted | `DataValuator` | 输出 `ValueEstimate`，不输出 Payment |
| learned linear/symbolic/reflective | `TrainableValuator` | 分开 `fit` 和 `value`，记录模型表达式与 reflection history |
| valuation runner | `DataValuator` 与 `PipelineRunner` 实现 | 完整迁入后拆分纯算法、I/O 与编排，移除源项目路径和配置耦合 |

### 2.4 DataPrice

DVMK 已实现：first-price、second-price、VCG、McAfee double auction、posted price、freshness adjusted posted price、menu pricing、externality VCG、budget feasible procurement、proportional share procurement、contribution fair-share、core-selecting package auction、contextual-bandit posted price、no-arbitrage projection，以及 bid normalization、capacity/demand、welfare、feasibility、critical payment helpers。

迁移目标：

| DVMK 内容 | DataValor 目标接口 | 具体改造 |
|---|---|---|
| bid/价格辅助函数 | `PricingModel` / `PricingMechanism` | 将浮点金额改为 `Money(Decimal, currency)`，拆分 quote 和 outcome |
| first/second/posted/freshness/menu | `PricingMechanism` | 统一 `PricingRequest`、`Allocation`、`Payment` 和 rights 输入 |
| McAfee/VCG/externality VCG | `PricingMechanism` | 保留外部性、单参数等假设，并单独标记尚待验证的性质 |
| budget/proportional/core/contribution | `PricingMechanism` | 保留 critical payment、core constraints、IR/budget/capacity diagnostics |
| contextual bandit | `OnlinePricingModel` | 拆成 `quote/observe`，显式记录曝光、接受、库存和状态 |
| no-arbitrage projection | `PriceConstraint` | 从机制中独立出来，保留投影前后价格和约束说明 |

### 2.5 DataMarket、Benchmark 与 Analysis

DVMK 已实现：truthful、fixed/adaptive shading、epsilon-greedy、budget pacing、multiplicative weights、best response、contextual shading；多轮 simulation、participant state、observation、state handoff；mechanism × bid policy × round × repetition benchmark；true welfare、reported-bid welfare、seller revenue、capacity/demand/payment checks；paired comparison、bootstrap interval、leaderboard、Pareto frontier 和 failure witness。

迁移目标：

| DVMK 内容 | DataValor 目标接口 | 具体改造 |
|---|---|---|
| bid strategy | `ParticipantStrategy.decide/observe` | 使用 `MarketObservation`，显式 bid/ask/state，不再传源项目字典 |
| simulation runner | `MarketSimulator.reset/step/run` | 分离 `MarketSnapshot`、step transition 和 report |
| `measure_outcome` | `BenchmarkMetric.measure` | 保留 true/reported welfare、revenue 和性质维度 |
| benchmark runner | `BenchmarkRunner.run` | case × component × repetition，raw observation 先于 aggregate |
| bootstrap、paired comparison | `Analyzer`/`ResultComparator` | 消费 artifact refs，并写明独立性和适用条件 |
| Pareto/frontier | `FrontierAnalyzer` | 明确目标方向和约束，保留 frontier 与 scalarized rank 的各自含义 |

## 3. 阶段计划

```text
Stage 00  盘点完整文件、公共接口
    ↓
Stage 01  公共产物、数据产品、数据源与扰动
    ↓
Stage 02  DataProf / DataEval / task utility
    ↓
Stage 03  DataValue / contribution / symbolic valuation
    ↓
Stage 04  DataPrice mechanisms and pricing models
    ↓
Stage 05  DataMarket simulation / Benchmark / Analysis
    ↓
Stage 06  DataValor 原生 CLI、示例、插件和发布集成
```

| 阶段 | 迁移的主要部分 | 目标 | 主要风险 |
|---|---|---|---|
| 00 | 完整文件清单、接口契约 | 让复制范围可追溯 | 文件遗漏、目标接口不一致 |
| 01 | core、data_product、distribution | 统一 artifact、数据引用和可复现输入 | 将 benchmark 数据源误当治理 |
| 02 | evaluation、task_utility、轻量 profile | 形成画像、质量和任务表现层 | 指标方向、可选依赖、模态输入 |
| 03 | valuation、requirements、contribution | 形成用户/任务估值层 | utility、贡献度和货币价值混淆 |
| 04 | pricing base/utils、机制实现 | 形成报价和清算层 | 机制假设、复杂度、金额精度 |
| 05 | simulation、benchmark、analysis | 形成市场实验与统计层 | 把仿真结果误写成理论证明 |
| 06 | CLI、配置、示例、插件 | 形成 DataValor 原生体验 | 清除源项目命名、协议和路径残留 |

每个阶段按“完整文件复制 → 目标接口实现 → schema 改造 → 测试迁移 → 新测试 → 源命名清理”的顺序推进。

## 4. 迁移记录模板

每一批完整复制并改造的代码都要在 `docs/migrations/dvmk/source_manifest.yaml` 增加条目：

```yaml
batch_id: stage_03_contribution_v1
source_directory: src/dvmk/valuation/
source_paths:
  - src/dvmk/valuation/contribution.py
source_symbols:
  - leave_one_out
  - monte_carlo_shapley
target_paths:
  - src/datavalor/data_value/contribution.py
target_interfaces:
  - datavalor.data_value.ContributionValuator
changes:
  - replaced source namespace and dict payload with typed ValuationTarget and ValueEstimate
  - separated utility evaluation from artifact writing
  - added convergence and budget diagnostics
tests_migrated:
  - tests/data_value/test_contribution_contract.py
status: planned
```

`status` 只有在目标代码已复制、改造、测试和审阅完成后才改成 `migrated`。

## 5. 每阶段验收和回滚

### 验收标准

- 目标代码统一使用 `datavalor.*` import；
- 全仓库源码、配置和示例完成 `dvmk`、`data_value_market_kit`、旧 protocol 与旧 CLI 命名的清理；
- 完整源文件已转换为 DataValor 语义，并补充改造后的新测试；
- artifact 包含 schema version、producer、parents、evidence 和 diagnostics；
- 可选依赖按能力按需加载；
- 算法与 I/O、配置、报告写入解耦；
- 文档说明假设、适用范围、复杂度以及需要单独验证的性质。

### 回滚

每一阶段都应当是独立 commit 或 feature branch。失败时只回滚 DataValor 阶段分支，不回退或覆盖 `/root/yusen/data_value_market_kit` 的用户改动。迁移完成后通过全仓库扫描清除源项目命名、旧 protocol 和固定路径残留。

## 6. 迁入后必须重构清理

- DVMK `cli.py`、runner 和配置完整迁入后，必须在 DataValor CLI、PipelineRunner 和配置层重新落位；
- 仅用于展示的 README、HTML、CSS、logo 和生成页面；
- 超大 outputs、缓存和临时数据：由外部存储管理；
- `__pycache__`、`.pytest_cache`、`.ruff_cache` 和本地 outputs；
- 源项目 protocol、命令名和固定路径作为 DataValor 公共 API；
- 任何让 DataValor 必须安装或导入 DVMK 才能运行的代码。
