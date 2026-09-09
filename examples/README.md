# DataValor 示例

这里的代码按一条实际业务链来组织：先回答“数据对谁有用”，再回答“应该怎样报价和交易”，最后验证“买到以后能否在权利范围内使用”。示例使用仓库已有的公共模型和基线实现，不需要联网，也不要求安装可选依赖。

在仓库根目录执行：

```bash
PYTHONPATH=src python examples/00_unified_value_chain.py
PYTHONPATH=src python examples/05_stage1_governance_profile_eval.py
PYTHONPATH=src python examples/06_stage1_unified_workflow.py
PYTHONPATH=src python examples/07_stage2_task_valuation.py
PYTHONPATH=src python examples/08_stage3_advanced_valuation.py
PYTHONPATH=src python examples/09_stage4_pricing_and_mechanisms.py
PYTHONPATH=src python examples/10_stage5_market_benchmark_analysis.py
PYTHONPATH=src python examples/11_stage7_multimodal_evaluation.py
PYTHONPATH=src python examples/12_datagov_lineage_rights_audit.py
PYTHONPATH=src python examples/13_dataprof_statistics_drift.py
PYTHONPATH=src python examples/14_dataeval_quality_gate.py
PYTHONPATH=src python examples/15_data_value_risk_portfolio.py
PYTHONPATH=src python examples/16_data_price_models_audit.py
PYTHONPATH=src python examples/17_data_market_lifecycle_incentive.py
PYTHONPATH=src python examples/18_data_market_mechanism_design.py
PYTHONPATH=src python examples/01_task_value_and_shapley.py
PYTHONPATH=src python examples/02_auction_and_budget_procurement.py
PYTHONPATH=src python examples/03_governed_query_with_redaction.py
PYTHONPATH=src python examples/04_market_strategy_sensitivity.py
```

`00_unified_value_chain.py` 是阶段 0 的主链路示例：它读取
`configs/workflows/stage0_unified.json`，把一份数据产品依次送入治理、画像、评估、估值、定价、交易、查询、使用计量和分析阶段。每个阶段都会在 `outputs/stage0-unified/` 写出一个带 `parents`、`schema_version`、`producer`、`status` 和 `diagnostics` 的 JSON artifact；运行摘要写入 `summary.json`。如果中途失败，runner 会额外写出 `workflow.failure` artifact，摘要会标记 `failed_stage`，默认不会继续执行后续必需阶段。

`05_stage1_governance_profile_eval.py` 是阶段 1 的独立质量工作流：读取包含重复、缺失值和类型错误的合成客户记录，实际运行元数据提取、内存目录、用途策略、敏感字段扫描、统计画像、版本差异和三项质量指标，结果写入 `outputs/stage1-quality-summary.json`。

`06_stage1_unified_workflow.py` 使用 `configs/workflows/stage1_quality.json` 和阶段 0 相同的统一 runner，将 DataGov、DataProf、DataEval 串成三个可追溯 stage；结果和每个阶段的 artifact 写入 `outputs/stage1-workflow/`。

`08_stage3_advanced_valuation.py` 在阶段 2 链路上增加质量调整估值、保守/基准/乐观情景、受限符号表达式、线性模型训练/预测、精确 Shapley、Group Shapley、两两交互和 Bootstrap 稳定性，再按贡献分摊总价值；结果写入 `outputs/stage3-valuation/`。

`09_stage4_pricing_and_mechanisms.py` 将估值证据转换为四种可解释报价，依次执行价格带和阶梯折扣约束，再用数量出价运行多单位统一价格拍卖；同一产品还通过质量/成本比排序的预算采购完成部分购买。脚本最后检查个体理性、预算可行和容量可行，并把完整 quote、allocation、payment、seller revenue、welfare 与诊断写入 `outputs/stage4-pricing/result.json`。对应配置为 `configs/workflows/stage4_pricing.json`；配置描述稳定的阶段顺序，脚本中的 handler 展示如何将领域实现接入统一 runner。

`10_stage5_market_benchmark_analysis.py` 在相同市场案例中运行 truthful、fixed shading、budget pacing 三种策略，使用稳定种子执行 5 次 × 3 个策略的矩阵实验，保留 15 条原始观测，再计算 bootstrap 区间、成对差异和收入/波动 Pareto 前沿。结果写入 `outputs/stage5-market/result.json`，对应配置为 `configs/workflows/stage5_market_benchmark.json`。这是一套有限样本实验工具，不将结果宣称为均衡或因果结论。

`11_stage7_multimodal_evaluation.py` 分别调用 tabular/text/image/audio/video/multimodal 文件中的指标，生成六组独立 `MetricResult`，保留各自的 score direction、统计量、证据和诊断。它覆盖表格 IQR 异常值与标签熵、文本重复率、图像像素范围、音频削波/静音、视频时序与隐私，以及多模态 checksum/时间对齐；结果写入 `outputs/stage7-evaluation/result.json`，对应配置为 `configs/workflows/stage7_multimodal_evaluation.json`。

`12_datagov_lineage_rights_audit.py` 使用同一套 DataGov 模型构造 v1/v2 元数据，比较字段删除、checksum 和权利收紧；再从 source 经 evaluation、valuation 连接到 quote，运行上下游影响分析。RightsMatrixEvaluator 同时检查用途、商业使用和司法辖区，最后把决策、发现、版本差异、血缘摘要和重新评估建议汇总为审计 bundle，写入 `outputs/datagov-extension/result.json`。

`13_dataprof_statistics_drift.py` 展示 DataProf 的描述性增强：对数值字段计算分位数、IQR、变异系数和 Tukey 异常围栏；对类别字段计算熵、Gini 集中度和 top-k 覆盖；对数值字段对计算 Pearson 相关；再用固定种子进行比例分层抽样，并以 PSI/JS divergence 比较两个快照的分布变化。结果写入 `outputs/dataprof-extension/result.json`，漂移报告只描述分布差异，不代替 DataEval 的质量结论。

`14_dataeval_quality_gate.py` 展示新增 DataEval 指标：数值业务范围合规、重复实体标签冲突、分组完整性差距、文本可读性，以及按照每个指标方向执行的 `EvaluationThresholdGate`。它保留每项指标的统计量和 evidence，最后输出是否通过验收门禁到 `outputs/dataeval-extension/result.json`。

`15_data_value_risk_portfolio.py` 展示 DataValue 的增量能力：`RiskAdjustedValuator` 将质量估计的不确定性换算成货币风险折扣，`CounterfactualValuator` 计算相对 baseline 的增量价值，`PortfolioValuator` 汇总多产品的协同与组合风险；示例还用单调经验曲线描述数据规模的边际价值，并用 MAE/RMSE/bias 校准估值与实际结果。结果写入 `outputs/datavalue-extension/result.json`。

`16_data_price_models_audit.py` 展示 DataPrice 的分段用量、订阅超额、风险调整和需求弹性报价，并用 `calibrate_quotes` 对照实际成交价、用 `audit_pricing_outcome` 检查支付对账。结果写入 `outputs/dataprice-extension/result.json`；参与者行为和多轮市场实验仍由 DataMarket 处理。

`17_data_market_lifecycle_incentive.py` 展示 DataMarket 的新增功能：对已激活挂牌按需求相关性排序、从交易记录计算供应商信誉、按贡献分配激励预算，并生成市场快照统计。它不重新计算价格，结果写入 `outputs/datamarket-extension/result.json`。

`18_data_market_mechanism_design.py` 展示市场侧机制设计：先用价格—时间优先的订单簿匹配检查挂牌状态和质量门槛，再把订单交给 DataPrice 清算；随后审计个体理性、预算平衡和配置效率，按买方配额裁剪交付及支付，最后用带联盟协同项的 Shapley 边际贡献分配收入。结果写入 `outputs/datamarket-mechanism-design/result.json`。匹配和准入不会修改报价模型，便于将同一机制替换为线上订单簿或人工复核流程。

这些脚本分别覆盖：

1. 统一主链路：治理、画像、评估、估值、定价、市场、查询、使用计量和分析；
2. 面向任务的效用估值与样本边际贡献（LOO、精确 Shapley、Monte Carlo Shapley）；
3. 将估值转成买方 bid，比较二价、McAfee 双边拍卖和预算可行采购；
4. 在查询前做用途/权利检查，查询后做字段脱敏和行数限制；
5. 在有限轮市场中比较真实出价、固定 shading 和预算 pacing 的成交与福利。
6. 用统一 runner 将阶段 1 的治理、画像、评估结果写成可追溯 artifact。
7. 在阶段 1 证据之上运行买方任务估值、LOO/Shapley 类贡献度和价值解释。
8. 使用阶段 3 的安全符号表达式、线性学习型估值、精确 Shapley 和贡献价值分摊。
9. 按模态运行表格、文本、图像、音频、视频和多模态质量评估。

脚本输出 JSON，方便直接接入 notebook、CI 或后续的 artifact store。示例中的数据都是合成数据；接入真实数据时，应在 `DataReference` 中补充 schema、checksum、来源和许可证信息。

## 每个例子具体做了什么

### 01：任务效用和数据贡献

脚本把 5 条带有区域、标签和新鲜度的记录作为一个训练数据产品，定义一个透明的下游效用函数（覆盖率、区域多样性、标签平衡、新鲜度），再用同一函数跑四种估值口径。输出中的 `components`、`utility_calls`、`samples` 和 `std_error` 可直接用于采购排序或标注返工队列。把 `utility` 换成真实模型在留出集上的 AUC/损失，即可进行模型相关估值；样本超过 10 条时应使用 Monte Carlo 或 pyDVL adapter。

### 02：拍卖和预算采购

三个买方对同一气象产品提交支付意愿，三个供应方提交保留价。脚本分别运行二价拍卖、McAfee 双边拍卖和 500 元预算下的采购机制，并打印 allocation、payment、welfare（采购基线未定义买方价值时为 `null`）和 seller revenue。这个例子适合做机制对比和回放测试；生产化时还要增加多产品互补/替代约束、税费、结算失败和支付凭证。

### 03：受治理查询

查询请求先经过 `RightsQueryAuthorizer`，再由注入的 Vanna 风格 planner 生成 SQL，内存 executor 返回记录，最后由 `QueryResultGuard` 对 email 脱敏并限制最多 2 行。脚本同时展示允许和拒绝两条路径，拒绝时不会调用 executor。将 planner/executor 换成企业 SQL、DB-GPT 或 PySyft 后，仍可沿用相同的授权与审计结构。

### 04：市场策略敏感性

同一个买方价值 500 元、预算 600 元，连续 8 轮使用 first-price auction，分别比较 truthful、0.85 固定 shading 和 budget pacing。输出成交轮数、成交率、卖方收入和报告福利；它是实验观察，不是均衡证明。将 `rounds`、买方数量、卖方 ask、随机种子和策略参数放入 benchmark 配置，就能扩展成批量敏感性实验。

## 示例与真实部署的替换点

示例把“可替换的外部系统”集中在很小的函数里：效用函数可以换成训练集上的 AUC/损失下降，拍卖机制可以换成自定义 `PricingMechanism`，查询脚本中的 planner/executor 可以替换为 DB-GPT、Vanna、SQL 引擎或 PySyft executor。这样既能复现实验，也不会把某个供应商 SDK 写死在业务模型中。

更完整的行业背景、方法选择和能力边界见 [数据估值定价调研与 DataValor 能力地图](../docs/research/data_valuation_pricing_landscape.md)。
