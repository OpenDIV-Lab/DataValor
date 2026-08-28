# `data_value_market_kit` 完整代码迁移与改造方案

> 逐阶段的源文件清单、接口字段、测试门禁和验收流程见
> [DVMK 源码迁移执行手册](../migrations/dvmk/README.md)；机器可读计划见
> [configs/migrations/dvmk/plan.yaml](../../configs/migrations/dvmk/plan.yaml)。


## 一、已明确的复用方式

DVMK **不是** DataValor 的运行时后端，也不计划通过 adapter、CLI 或 `import dvmk` 直接调用。

正确路线是：将 DVMK 中现有实现文件整体复制到 DataValor 对应模块，再按照 DataValor 的总体概念体系、目录结构、命名规范和统一产物协议进行实质性改造，最终成为 `datavalor.*` 的原生实现。DVMK 的 protocol、CLI 命名和目录编排只作为重构输入，不作为目标 API。

```text
DVMK 候选源码
  -> 盘点完整文件和依赖关系
  -> 确认 DataValor 目标模块
  -> 复制到 DataValor 目标模块
  -> 重命名、拆分、去耦和统一 schema
  -> 迁移并扩展测试
  -> 完成 DataValor 命名、接口和测试改造
  -> 成为 DataValor 原生代码
```

迁移完成后应满足：

- DataValor 的运行不要求安装 `data-value-market-kit`；
- `src/datavalor` 中不存在 `from dvmk ...` 或 `import dvmk`；
- 用户只接触 `datavalor.*` API、配置和产物 schema；
- 被迁移代码的源文件、目标文件和主要改动均可追溯；
- DVMK 后续变化不会自动影响 DataValor，双方不承担运行时兼容义务。

## 二、按 DataValor 模块完整迁入

| DataValor 模块 | 源实现内容 | 匹配度 | 迁移决策 |
|---|---|---:|---|
| DataGov | `data_product`、distribution manifest、SHA-256 校验、run metadata、artifact lineage、本地数据适配器 | 部分匹配 | 完整迁入后拆成数据产品、provenance 和 benchmark 数据构造能力，不把它包装成完整合规治理系统 |
| DataProf | 模态 metadata、基础统计量和部分 evaluation statistics | 部分/较低 | 完整迁入相关实现文件，再将统计、schema 推断与画像接口拆分；DataProf 的完整画像契约按 DataValor 重新实现 |
| DataEval | `BaseMetric`、`MetricResult`、registry、文本/图像/音频/视频/多模态指标、task utility | 高 | 重点迁移；统一为 DataValor 组件协议、结果 schema、可选依赖和证据模型 |
| DataValue | `BaseValuator`、`ValueResult`、需求导入、LOO/Shapley/Banzhaf、学习型和符号型价值函数 | 高 | 重点迁移；保留用户、任务、权利、成本和不确定性语义，重新梳理质量分数与估值的边界 |
| DataMarket | 市场 benchmark、报价策略、多轮市场、参与者状态和策略仿真 | 高 | 重点迁移；拆分市场主体、策略、环境、市场状态和实验 runner |
| DataPrice | `BaseMarketMechanism`、`PricingResult`、拍卖、采购、动态定价与支付计算 | 高 | 重点迁移；合并重复机制、规范命名，并逐个补充假设、性质和规模边界 |
| DataQuery | DVMK 当前没有受治理的自然语言数据访问或数据智能体执行层 | 低 | 不从 DVMK 迁移；由 DataValor 独立设计或参考其他开源项目实现 |
| Toolkit | config、I/O、plugins、benchmark metrics、statistics、bootstrap、Pareto frontier、lineage | 高 | 完整迁入并重构为跨模块公共能力；CLI 和 runner 在 DataValor 中重新落位 |

## 三、建议的源文件到目标目录映射

### 1. 公共协议与基础设施

| DVMK 来源 | DataValor 建议目标 | 改造要求 |
|---|---|---|
| `dvmk/core/artifacts.py`、`io.py`、`run_metadata.py` | `datavalor/core/artifact.py`、`datavalor/core/interfaces.py`、`datavalor/core/context.py` | 统一 `ArtifactEnvelope`、schema version、checksum、运行环境和 lineage；去除 DVMK 固定目录假设 |
| `dvmk/core/config.py`、`deps.py` | `configs/` + `datavalor.core.RunContext`/`PipelineSpec` | 只提取配置校验和可选能力检测，按 DataValor 模块拆分配置；不迁移 DVMK 巨型配置 schema |
| `dvmk/core/plugins.py` | 各 `datavalor.data_*/registry.py` + `datavalor.core.Registry` | 保留可发现组件的元数据、版本、能力声明和安全边界，不保留 DVMK plugin protocol |
| 各模块 `base.py` | 对应的 `datavalor/data_*/interfaces.py` | 保留 Evaluation、Valuation、Pricing、Simulation 的语义分离；抽取共同字段，但不强行合并成一个通用标量结果 |
| 各模块 `registry.py` | 对应的 `datavalor/data_*/registry.py` | 统一注册接口、命名冲突处理、lazy import 和可选依赖错误信息 |

### 2. DataGov 与 benchmark 数据构造

| DVMK 来源 | DataValor 建议目标 | 改造要求 |
|---|---|---|
| `dvmk/data_product/` | `datavalor/data_gov/data_product/` | 保留本地格式适配、canonical hash 和 manifest；补充权利、来源、许可、敏感级别和保留策略字段 |
| `dvmk/distribution/providers/` | `datavalor/toolkit/benchmark/data_sources/` | 把真实/合成 provider 定位为研究数据源，不等同于 DataGov 本身 |
| `dvmk/distribution/transforms/` | `datavalor/toolkit/benchmark/data_perturbations/` | 保留 shift、noise、split 和重采样逻辑；输出完整随机种子、参数和变换审计 |
| `dvmk/distribution/runner.py` | `datavalor/toolkit/benchmark/` 与 `PipelineRunner` 实现 | 完整迁入后拆分编排、产物写入和数据变换，移除源路径耦合 |

### 3. DataEval

以下目录中的实现文件整体迁入，再按 DataValor 接口拆分：

- `dvmk/evaluation/base.py`、`registry.py`、`artifacts.py`；
- `common/embedding_mmd.py`、`cleanlab_issues.py`、`contribution.py`；
- `task_utility/` 下的任务效用协议、cache 和 sklearn task；
- 文本、图像、音频、视频和多模态目录中具有明确输入输出与测试的指标。

迁移时需要：

- 区分 dataset、sample、group、source、window 等粒度；
- 把质量分数、原始统计量、证据文件和诊断信息分别保存；
- 将 Cleanlab、LiteLLM、OpenCV 等保持为 DataValor 的可选依赖；
- 审核每个指标的归一化方向、数值范围、缺失输入行为和确定性；
- 不把“可计算”直接表述为“已经具备理论有效性或生产适用性”。

### 4. DataValue

以下目录中的实现文件整体迁入，再按 DataValor 接口拆分：

- `dvmk/valuation/base.py`、`registry.py`、`requirements.py`；
- `contribution.py` 中的 LOO、Shapley、Banzhaf 逻辑；
- `expression.py`、`symbolic.py`；
- `value_functions/` 中的 contribution-adjusted、distribution-preview、learned-linear、reflective-symbolic 和 weighted-user-task 方法。

主要改造方向：

- 为算法增加统一的 `fit/evaluate/value` 生命周期或更小的能力协议；
- 明确 sample、group、dataset、data product 等估值对象；
- 明确 model-dependent、model-agnostic、task-specific 和 market-oriented 类型；
- 增加不确定性、收敛状态、计算预算、随机种子和解释字段；
- 将 DVMK 自有贡献度实现与未来 pyDVL/OpenDataVal 算法放入同一 benchmark，而不是混成一套不注明来源的实现。

### 5. DataPrice

`dvmk/pricing/mechanisms/` 中的机制实现整体迁入，但不能原样作为公共 API；应在迁入过程中完成去重、命名和接口审核：

- 基础拍卖：first-price、second-price、VCG、McAfee double auction；
- 发布价与菜单定价：posted price、freshness-aware posted price、menu pricing；
- 采购与分配：budget procurement、proportional-share procurement、contribution fair-share；
- 复杂机制：core-selecting auction、externality VCG；
- 动态定价：contextual-bandit posted price；
- 价格约束：no-arbitrage projection。

每种机制迁移时都应补充：

- 输入市场类型、单参数/多参数假设、供给和需求约束；
- allocation、payment、seller revenue、welfare 的统一定义；
- individual rationality、budget balance、capacity feasibility 等可执行性质检查；
- DSIC、BIC、core、equilibrium 等不能由运行结果直接证明的性质说明；
- 精确算法或枚举算法的时间复杂度和最大建议规模。

### 6. DataMarket 与 Toolkit

| DVMK 来源 | DataValor 建议目标 | 改造要求 |
|---|---|---|
| `dvmk/simulation/base.py`、`strategies.py` | `datavalor/data_market/simulation/interfaces.py` 与 `models.py` | 把 bidder policy 改造成 `ParticipantStrategy.decide/observe`，使用 typed observation/state |
| `dvmk/simulation/runner.py` | `datavalor/data_market/simulation/interfaces.py` 的 `MarketSimulator` 实现 | 改用 DataValor 市场和产物 schema，不保留 DVMK 路径耦合 |
| `dvmk/benchmark/metrics.py` | `datavalor/toolkit/benchmark/interfaces.py` 的 `BenchmarkMetric` 实现 | 保留 welfare、revenue 和性质检查，统一真实价值与 reported bid 的区别 |
| `dvmk/benchmark/runner.py` | `datavalor/toolkit/benchmark/interfaces.py` 的 `BenchmarkRunner` 实现 | 拆分实例生成、机制执行、重复实验、聚合与产物写入，避免单文件继续膨胀 |
| `dvmk/analysis/statistics.py` | `datavalor/toolkit/analysis/interfaces.py` 的 `Analyzer`/`ResultComparator` 实现 | 保留 paired bootstrap 等通用统计能力，补充适用条件和失败诊断 |
| `dvmk/analysis/frontier.py` | `datavalor/toolkit/analysis/interfaces.py` 的 `FrontierAnalyzer` 实现 | 迁移 Pareto 分析；明确最大化/最小化方向与性质约束 |

## 四、完整迁入时需要重构的内容

- `dvmk/cli.py`：完整文件迁入后改造成 DataValor CLI，不保留原命令名和四层流程假设。
- 各模块现有 `runner.py`：完整文件迁入后拆分为 DataValor 的 pipeline、simulation 和 benchmark 组件，解除配置、I/O 与报告写入耦合。
- DVMK 的全部 YAML 配置：完整迁入配置内容，再转换到 DataValor schema 和模块级配置文件。
- 示例数据和 outputs：代码文件可以完整迁入；数据、模型和大体积 outputs 仍需单独确认体积、隐私和可再分发范围。
- `__pycache__`、缓存和本地生成产物：禁止迁移。
- 与新模块语义不匹配的 README 和历史阶段描述：只保留研究依据，面向 DataValor 重新编写文档。


## 六、建议的实施批次

### 第 0 批：确定来源与公共契约

1. 盘点当前 DVMK 工作区的完整实现文件。
2. 建立迁移 manifest，记录源文件到目标文件的完整覆盖关系。
3. 冻结 DataValor 的 component、context、artifact、registry 基础协议。
4. 明确各模块结果不能被压缩成同一个通用标量。

### 第 1 批：基础类型和代表性闭环

1. 完整迁移并改造 Evaluation、Valuation、Pricing、Simulation 的基础类型和 registry。
2. 完整迁移公共 artifact、I/O、run metadata，再按 DataValor 边界拆分。
3. 每个核心模块建立代表算法和完整文件覆盖的端到端测试。
4. 检查 DataValor 对 DVMK 的运行时依赖为零。

### 第 2 批：数据评估与估值算法

1. 完整迁移 DataEval 的指标和 task utility，再按 DataValor 接口拆分。
2. 完整迁移 DataValue 的需求导入、贡献度和符号/学习型方法。
3. 建立统一估值 benchmark，用于比较迁移算法与后续外部算法。

### 第 3 批：定价、市场与分析

1. 将 pricing mechanisms 全部迁入，完成去重、分类和接口改造。
2. 完整迁入报价策略、市场仿真、benchmark metrics 和统计分析。
3. 为每种机制补性质测试、失败 witness 和规模边界。

### 第 4 批：数据产品与可选模态

1. 完整迁入 data product、provenance 和 benchmark 数据构造能力。
2. 按真实需求选择 Cleanlab、LiteLLM、OpenCV 等可选算子。
3. 最后再设计 CLI、Web UI 和完整示例，避免界面先于协议定型。

## 七、每批迁移的验收条件

- 所有目标代码使用 `datavalor.*` import，不依赖或导入 `dvmk`；
- 迁移 manifest 能追溯源路径、目标路径和改造内容；
- 所有完整源文件均已转换为 DataValor 语义，并针对改造后的接口补充新测试；
- 算法层不直接读写固定输出目录，I/O 与计算逻辑分离；
- 可选依赖缺失时给出明确错误，不在 import 阶段加载重型依赖；
- artifact 包含 schema version、配置、随机种子、依赖版本、输入摘要和 diagnostics；
- 文档明确算法假设、适用范围、复杂度和不能由实验直接证明的性质；
- `pytest`、静态检查和最小端到端测试全部通过。
