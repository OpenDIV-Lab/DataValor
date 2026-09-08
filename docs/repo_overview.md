# DataValor 当前功能概览

DataValor 是一个围绕“数据能否被管理、评估、估值、定价并安全使用”组织的 Python 工具库。仓库采用 `src/datavalor/` 源码布局，各模块通过统一的数据产品、运行上下文和 artifact 引用连接起来；研究者可以只使用其中一个模块，也可以运行完整价值链。

## 公共基础

`src/datavalor/core/` 提供所有模块共用的基础契约和轻量基础设施。`core/models.py` 定义 `DataProduct`、`DataReference`、`RightsBundle`、`ActorProfile` 和 `TaskContext`；`core/artifact.py` 定义带版本、父引用、证据和状态的 `ArtifactEnvelope`；`core/context.py` 定义可复现运行所需的 `RunContext`。`core/registry.py` 提供延迟创建和能力发现，`core/workflow.py` 提供按配置执行阶段、保留父产物引用和失败诊断的统一运行器，`core/artifact_store.py` 提供本地 artifact 存储。

## 价值发现模块

### DataGov：数据治理与可用性

源码位于 `src/datavalor/data_gov/`。`builtins.py` 中的 `LocalMetadataExtractor`、`InMemoryMetadataCatalog`、`RightsPolicyEvaluator` 和 `SensitiveFieldScanner` 分别完成元数据提取、目录检索、用途/期限/商业权利检查和敏感字段发现。

治理增强实现位于：

- `data_gov/lineage.py`：构建 source、data product、evaluation、valuation、quote 之间的血缘图，支持上下游追踪、拓扑排序、循环检测、影响产物筛选和稳定 digest；
- `data_gov/rights_matrix.py`：结合产品权利、买方 `ActorProfile`、任务 `TaskContext`、操作、辖区和到期时间，返回 `allow`、`deny` 或 `review`；
- `data_gov/version_diff.py`：比较 schema、字段约束、checksum、记录数、来源和权利变化，并给出是否需要重新评估、重新估值或重新报价的标志；
- `data_gov/audit.py`：将治理报告、安全报告、元数据、血缘摘要、版本差异和 artifact 引用汇总为可序列化审计 bundle。

### DataProf：描述性统计画像

源码位于 `src/datavalor/data_prof/`。`builtins.py` 中的 `BasicDataProfiler` 生成字段类型、缺失数、基数、数值统计和类别频率，`BasicProfileComparator` 比较两个数据版本的描述性变化。

`data_prof/advanced.py` 增加了稳健分位数/IQR、Tukey 异常围栏、类别熵和集中度、Pearson 相关性、固定种子分层抽样，以及数值 PSI/类别 JS 分布漂移分析。这些结果描述“数据是什么样、版本如何变化”，不直接替代 DataEval 的质量判断。

### DataEval：质量和任务表现评估

源码位于 `src/datavalor/data_eval/`。`builtins.py` 提供完整性、重复率、字段有效性和多指标 `CompositeEvaluator`；`tabular.py`、`text.py`、`image.py`、`audio.py`、`video.py` 与 `multimodal.py` 分别提供表格、文本、图像、音频、视频和多模态指标。

`data_eval/advanced.py` 进一步提供业务数值范围合规、重复实体标签冲突、群组完整性差距、无第三方依赖的文本可读性，以及按指标方向执行的 `EvaluationThresholdGate`。每个指标都返回 `MetricResult`，保留 score direction、scope、statistics、evidence 和 diagnostics。

### DataValue：任务相关估值与数据贡献

源码位于 `src/datavalor/data_value/`。`valuators.py` 和 `value_functions.py` 支持基于买方任务效用的估值；`contribution.py` 支持 leave-one-out、精确 Shapley 和 Monte Carlo Shapley；`contribution_advanced.py` 提供 Banzhaf、分组 Shapley、两两交互和 Bootstrap 稳定性；`advanced_valuation.py` 提供质量调整、情景估值、受限表达式和线性学习型估值；`extensions.py` 增加风险调整、反事实增量、组合协同、价值曲线和估值校准。该模块输出用户/任务相关的价值和贡献，不直接产生交易价格。

## 价值流通模块

### DataPrice：报价、拍卖和支付计算

源码位于 `src/datavalor/data_price/`。`pricing_models.py` 提供 cost-plus、value-based、usage-based、质量/新鲜度和在线需求调整报价；`extensions.py` 补充分段用量、订阅超额、风险调整和弹性报价，以及报价校准和支付对账；`constraints.py` 提供价格带和数量折扣约束；`mechanisms.py` 与 `mechanisms_advanced.py` 提供 posted price、二价、VCG、McAfee、多单位统一价格拍卖、预算采购和质量感知采购；`properties.py` 用于检查个体理性、预算可行性和容量可行性。

### DataMarket：市场参与和仿真

源码位于 `src/datavalor/data_market/`。该模块管理数据产品挂牌、参与者、买卖双方行为、收益分配和有限轮市场实验。`data_market/simulation/` 中包含 truthful、shading、budget pacing、epsilon-greedy、multiplicative weights、UCB 和 contextual shading 等策略，可用于比较成交率、收入、支出、福利和策略行为。

## 价值实现模块

### DataQuery：受治理的数据使用

源码位于 `src/datavalor/data_query/`。模块接口覆盖查询授权、查询规划、查询执行、结果脱敏/行数限制和数据智能体调用边界。示例中可将 planner/executor 替换为企业 SQL、DB-GPT、Vanna 或其他受控执行后端，治理检查和结果防护保持在 DataValor 契约内。

## Benchmark、分析和可选后端

`src/datavalor/toolkit/benchmark/` 提供数据源、扰动、实验矩阵和 benchmark 指标；`src/datavalor/toolkit/analysis/` 提供 bootstrap 区间、策略比较、regret 和 Pareto frontier；`src/datavalor/toolkit/webui/` 提供与具体 Web 框架无关的 view/app 接口。`src/datavalor/*/backends/` 中的 DataHub、OpenMetadata、Cleanlab、Evidently、Great Expectations、TorchMetrics 等连接器采用可选依赖和 adapter 方式，未安装第三方包时核心模块仍可导入。

## 运行入口和资料位置

- `examples/00_unified_value_chain.py`：运行治理、画像、评估、估值、定价、市场、查询和使用计量的统一链路；
- `examples/05_stage1_governance_profile_eval.py`、`06_stage1_unified_workflow.py`：治理、画像和质量评估；
- `examples/07_stage2_task_valuation.py`、`08_stage3_advanced_valuation.py`：任务估值、Shapley 和高级估值；
- `examples/09_stage4_pricing_and_mechanisms.py`、`10_stage5_market_benchmark_analysis.py`：报价、拍卖、采购和市场实验；
- `examples/11_stage7_multimodal_evaluation.py`：多模态质量指标；
- `examples/12_datagov_lineage_rights_audit.py`：DataGov 血缘、权利和版本审计；
- `examples/13_dataprof_statistics_drift.py`：DataProf 统计、抽样和漂移；
- `examples/14_dataeval_quality_gate.py`：DataEval 业务约束和阈值门禁。

对应配置位于 `configs/workflows/`，合成输入位于 `data/examples/`，测试位于 `tests/`，专题说明位于 `docs/research/`。完整示例运行说明见 `examples/README.md`，模块契约和边界见 `docs/architecture.md`。
